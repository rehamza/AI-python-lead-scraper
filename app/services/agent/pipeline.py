"""The AI lead-gen agent.

One run executes an iterative loop:

    plan (Claude) -> search (provider chain) -> triage (dedupe/filter)
      -> qualify + extract (Claude, structured output) -> enrich (crawl emails)
      -> verify (MX/SMTP) -> persist (Postgres)
      -> loop back to plan with feedback until target met, iterations exhausted,
         or two consecutive iterations yield no new leads (diminishing returns)

Target lead count defaults to the campaign's target_leads_per_run, but a run
can override it (see Run.target_leads / RunCreate) — e.g. "get me 500 this
time" — in which case the iteration budget auto-scales (see
_effective_max_iterations) so a bigger ask isn't capped by a small default.

Duplicate leads are prevented per-campaign via a persistent dedupe key
(company domain / LinkedIn URL / name) loaded fresh from the DB at the start
of every run — so reruns of the same campaign only ever add NEW leads.

This is deliberately a plain async pipeline rather than a LangGraph graph:
the flow is linear with a single feedback edge, so explicit code stays easier
to debug, test and extend. All the "intelligence" lives in the Claude calls.
"""
import asyncio
import logging
import math
import re
from datetime import datetime, timezone
from urllib.parse import urlparse

import anthropic
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.config import get_settings
from app.database import SessionLocal
from app.models import Campaign, EmailStatus, Lead, Run, RunStatus
from app.schemas import LeadAssessment, QualifiedBatch, QueryPlan
from app.services import llm
from app.services.agent import prompts
from app.services.enrichment.crawler import (
    crawl_site_for_emails,
    extract_domain,
    generate_pattern_candidates,
    rank_emails,
)
from app.services.enrichment.verifier import find_best_verified
from app.services.search import SearchResult, get_search_chain

log = logging.getLogger(__name__)

# Domains that can never be a lead's own website
AGGREGATOR_DOMAINS = {
    "linkedin.com", "crunchbase.com", "twitter.com", "x.com", "facebook.com",
    "instagram.com", "youtube.com", "medium.com", "reddit.com", "github.com",
    "angel.co", "wellfound.com", "techcrunch.com", "news.ycombinator.com",
    "google.com", "wikipedia.org", "glassdoor.com", "indeed.com", "producthunt.com",
    "g2.com", "betalist.com", "pitchbook.com", "apollo.io", "zoominfo.com",
    "clutch.co", "upwork.com", "quora.com", "substack.com", "eu-startups.com",
    "tech.eu", "sifted.eu", "dealroom.co", "f6s.com",
}

# In-process registry of live run tasks (single-process deployment)
RUNNING_TASKS: dict[int, asyncio.Task] = {}

# Hard ceiling on iterations even when a run's target_leads override implies
# many more — bounds cost/runtime for a mistaken huge request.
MAX_ITERATIONS_CEILING = 25

# Stop early if this many consecutive iterations save zero new leads — the
# search space is exhausted for this campaign, so further iterations would
# just burn LLM calls for no gain.
ZERO_YIELD_STOP_THRESHOLD = 2


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _root_domain(url: str) -> str:
    netloc = urlparse(url).netloc.lower().removeprefix("www.")
    parts = netloc.split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else netloc


def _name_slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


def _dedupe_key(assessment: LeadAssessment, domain: str = "") -> str:
    """Canonical per-campaign identity: company domain when known (pass the
    post-discovery domain so reruns that find the site directly still dedupe),
    else LinkedIn URL, else normalized company name."""
    domain = domain or extract_domain(assessment.website)
    if domain and _root_domain(f"https://{domain}") not in AGGREGATOR_DOMAINS:
        return domain
    if assessment.linkedin_url:
        return assessment.linkedin_url.rstrip("/").lower()
    return f"name:{assessment.company_name.strip().lower()}"


class AgentRun:
    def __init__(self, run_id: int):
        self.run_id = run_id
        self.settings = get_settings()
        self.stats: dict = {
            "queries_planned": 0,
            "searches_executed": 0,
            "results_collected": 0,
            "candidates_after_triage": 0,
            "qualified": 0,
            "leads_saved": 0,
            "websites_discovered": 0,
            "emails_found": 0,
            "emails_verified": 0,
            "iterations": [],
        }
        self.tried_queries: list[str] = []
        self.query_yield: dict[str, int] = {}
        self.seen_keys: set[str] = set()

    # ------------------------------------------------------------------ #
    async def execute(self) -> None:
        async with SessionLocal() as db:
            run = await db.get(Run, self.run_id)
            campaign = await db.get(Campaign, run.campaign_id)
            run.status = RunStatus.running
            run.started_at = _now()
            await db.commit()
            brief = campaign.agent_brief()
            campaign_id, min_score = campaign.id, campaign.min_score
            target = run.target_leads or campaign.target_leads_per_run
            max_iterations = self._effective_max_iterations(campaign, target)
            queries_per_iteration = campaign.queries_per_iteration
            results_per_query = campaign.results_per_query

            # Pre-load existing dedupe keys so reruns find NEW leads (this is the
            # cross-run "memory" that keeps duplicate companies out of the same
            # campaign — reloaded fresh from the DB at the start of every run).
            existing = await db.execute(select(Lead.dedupe_key).where(Lead.campaign_id == campaign_id))
            self.seen_keys = set(existing.scalars())

        saved_total = 0
        consecutive_zero_yield = 0
        try:
            for iteration in range(1, max_iterations + 1):
                iter_stats = {"iteration": iteration}
                await self._update_run(iteration=iteration)

                # 1. PLAN — Claude designs the queries
                plan = await self._plan(brief, queries_per_iteration, saved_total, target)
                iter_stats["queries"] = len(plan.queries)

                # 2. SEARCH — provider chain, bounded concurrency
                results_by_query = await self._search_all(plan, results_per_query)
                collected = sum(len(v) for v in results_by_query.values())
                self.stats["results_collected"] += collected
                iter_stats["results"] = collected

                # 3. TRIAGE — cheap dedupe before spending LLM tokens
                candidates = self._triage(results_by_query)
                self.stats["candidates_after_triage"] += len(candidates)
                iter_stats["candidates"] = len(candidates)

                # 4. QUALIFY — Claude scores and extracts, in batches
                qualified = await self._qualify(brief, candidates, min_score)
                self.stats["qualified"] += len(qualified)
                iter_stats["qualified"] = len(qualified)

                # 5+6. ENRICH & VERIFY & 7. PERSIST
                saved = await self._enrich_verify_persist(qualified, campaign_id)
                saved_total += saved
                iter_stats["saved"] = saved
                self.stats["leads_saved"] = saved_total
                self.stats["iterations"].append(iter_stats)
                await self._update_run()

                log.info("run %s iter %s: %s new leads (total %s/%s)",
                         self.run_id, iteration, saved, saved_total, target)
                if saved_total >= target:
                    break

                consecutive_zero_yield = consecutive_zero_yield + 1 if saved == 0 else 0
                if consecutive_zero_yield >= ZERO_YIELD_STOP_THRESHOLD:
                    log.info("run %s: stopping early after %d iterations with no new leads",
                             self.run_id, consecutive_zero_yield)
                    break

            await self._finish(RunStatus.completed)
        except asyncio.CancelledError:
            await self._finish(RunStatus.cancelled)
            raise
        except Exception as exc:  # noqa: BLE001 — persist any failure on the run row
            log.exception("run %s failed", self.run_id)
            await self._finish(RunStatus.failed, error=f"{type(exc).__name__}: {exc}")

    @staticmethod
    def _effective_max_iterations(campaign: Campaign, target: int) -> int:
        """Scale up the iteration budget when a run asks for more leads than the
        campaign's configured default, so e.g. requesting 1000 leads on a
        campaign tuned for 50/run doesn't just stop after 3 iterations."""
        base = campaign.max_iterations
        default_target = campaign.target_leads_per_run
        if target <= default_target or default_target <= 0:
            return base
        scale = math.ceil(target / default_target)
        return min(base * scale, MAX_ITERATIONS_CEILING)

    # ------------------------------------------------------------------ #
    async def _plan(self, brief: dict, n_queries: int, saved: int, target: int) -> QueryPlan:
        feedback = None
        if self.tried_queries:
            productive = sorted(self.query_yield.items(), key=lambda kv: kv[1], reverse=True)
            feedback = {
                "leads_saved_so_far": saved,
                "target": target,
                "queries_already_tried": self.tried_queries[-60:],
                "query_yield_qualified_leads": dict(productive[:20]),
            }
        plan = await llm.structured(
            system=prompts.PLANNER_SYSTEM,
            prompt=prompts.planner_prompt(brief, n_queries, feedback),
            output_format=QueryPlan,
        )
        plan.queries = plan.queries[:n_queries]
        self.stats["queries_planned"] += len(plan.queries)
        self.tried_queries.extend(q.query for q in plan.queries)
        return plan

    async def _search_all(self, plan: QueryPlan, per_query: int) -> dict[str, list[SearchResult]]:
        chain = get_search_chain()
        semaphore = asyncio.Semaphore(self.settings.agent_max_concurrent_searches)

        async def run_one(q) -> tuple[str, list[SearchResult]]:
            async with semaphore:
                try:
                    results = await chain.search(q.query, region=q.region, max_results=per_query)
                    self.stats["searches_executed"] += 1
                    return q.query, results
                except Exception as exc:  # noqa: BLE001 — a dead query shouldn't kill the run
                    log.warning("search failed for %r: %s", q.query, exc)
                    return q.query, []

        pairs = await asyncio.gather(*(run_one(q) for q in plan.queries))
        return dict(pairs)

    def _triage(self, results_by_query: dict[str, list[SearchResult]]) -> list[dict]:
        """Dedupe results and drop anything already known, keeping query provenance."""
        candidates: list[dict] = []
        seen_urls: set[str] = set()
        for query, results in results_by_query.items():
            for r in results:
                url_key = r.url.rstrip("/").lower()
                if not url_key or url_key in seen_urls:
                    continue
                seen_urls.add(url_key)
                root = _root_domain(r.url)
                # A result ON a company site we already captured is a duplicate
                if root and root not in AGGREGATOR_DOMAINS and root in self.seen_keys:
                    continue
                if url_key in self.seen_keys:
                    continue
                candidates.append({"query": query, "result": r})
        return candidates

    async def _qualify(self, brief: dict, candidates: list[dict], min_score: int) -> list[dict]:
        """LLM-qualify candidates in batches; returns [{assessment, candidate}]."""
        batch_size = self.settings.agent_qualify_batch_size
        qualified: list[dict] = []
        for start in range(0, len(candidates), batch_size):
            batch = candidates[start : start + batch_size]
            payload = [c["result"].as_prompt_dict(i) for i, c in enumerate(batch)]
            try:
                parsed: QualifiedBatch = await llm.structured(
                    system=prompts.QUALIFIER_SYSTEM,
                    prompt=prompts.qualifier_prompt(brief, payload),
                    output_format=QualifiedBatch,
                )
            except anthropic.BadRequestError as exc:
                # A 400 (bad schema/request) is deterministic — every remaining
                # batch would fail identically, so abort the run with a clear
                # error instead of burning searches and planner calls on
                # iterations that can never qualify anything.
                raise RuntimeError(f"qualification request rejected by the API: {exc}") from exc
            except Exception as exc:  # noqa: BLE001 — skip a bad batch, keep the run alive
                log.warning("qualification batch failed: %s", exc)
                continue
            batch_kept = 0
            near_misses: list[str] = []
            for a in parsed.assessments:
                a.score = max(0, min(100, a.score))
                if not a.is_lead or a.score < min_score:
                    if a.is_lead and a.company_name:
                        near_misses.append(f"{a.company_name}={a.score}")
                    continue
                if 0 <= a.result_index < len(batch):
                    candidate = batch[a.result_index]
                    qualified.append({"assessment": a, "candidate": candidate})
                    self.query_yield[candidate["query"]] = self.query_yield.get(candidate["query"], 0) + 1
                    batch_kept += 1
            top_scores = sorted((a.score for a in parsed.assessments), reverse=True)[:5]
            log.info(
                "run %s: qualified %d/%d in batch (min_score=%d, top scores %s%s)",
                self.run_id, batch_kept, len(parsed.assessments), min_score, top_scores,
                f", near misses: {', '.join(near_misses[:3])}" if near_misses else "",
            )
        return qualified

    async def _discover_domain(self, company_name: str, sector: str) -> str:
        """One extra (free) search to find the company's own website when the
        qualifying snippet didn't reveal it — funding news links the news
        outlet, not the company. Only accept a domain whose name matches the
        company's: a wrong domain means crawling the wrong company's emails,
        which is worse than having no domain at all."""
        name = company_name.strip()
        slug = _name_slug(name)
        if len(slug) < 4:  # too short to match a domain confidently
            return ""
        query = f"{name} {sector} official website".strip()  # no operators -> free engines
        try:
            results = await get_search_chain().search(query, max_results=6)
        except Exception as exc:  # noqa: BLE001 — discovery is best-effort
            log.warning("website discovery failed for %r: %s", name, exc)
            return ""
        for r in results:
            host = extract_domain(r.url)
            if not host or _root_domain(r.url) in AGGREGATOR_DOMAINS:
                continue
            label = _name_slug(host.split(".")[0])
            if len(label) >= 4 and (slug in label or label in slug):
                self.stats["websites_discovered"] += 1
                log.info("run %s: discovered website %s for %r", self.run_id, host, name)
                return host
        return ""

    async def _enrich_verify_persist(self, qualified: list[dict], campaign_id: int) -> int:
        semaphore = asyncio.Semaphore(self.settings.agent_max_concurrent_crawls)

        async def enrich_one(item: dict) -> dict | None:
            a: LeadAssessment = item["assessment"]
            result: SearchResult = item["candidate"]["result"]

            domain = extract_domain(a.website)
            if domain and _root_domain(f"https://{domain}") in AGGREGATOR_DOMAINS:
                domain = ""
            if not domain:
                if _dedupe_key(a) in self.seen_keys:  # already known — don't waste a search
                    return None
                domain = await self._discover_domain(a.company_name, a.sector)

            key = _dedupe_key(a, domain=domain)
            if key == "name:":  # no domain, no LinkedIn, no company name — nothing to contact
                log.info("run %s: skipping unactionable lead from %s", self.run_id, result.url)
                return None
            if key in self.seen_keys:
                return None
            self.seen_keys.add(key)

            email, status, candidates_audit, source = "", EmailStatus.not_found, [], ""
            if domain:
                async with semaphore:
                    found = rank_emails(await crawl_site_for_emails(domain))
                guesses = generate_pattern_candidates(a.contact_name, domain) if a.contact_name else []
                guesses = [g for g in guesses if g not in found]
                all_candidates = found + guesses
                if all_candidates:
                    email, status, candidates_audit = await find_best_verified(
                        all_candidates, guesses_from=len(found)
                    )
                    source = "website" if email in found else ("pattern" if email else "")
            return {
                "assessment": a,
                "result": result,
                "dedupe_key": key,
                "domain": domain,
                "email": email,
                "email_status": status,
                "email_source": source,
                "email_candidates": candidates_audit,
            }

        enriched = [e for e in await asyncio.gather(*(enrich_one(i) for i in qualified)) if e]

        saved = 0
        async with SessionLocal() as db:
            for e in enriched:
                a: LeadAssessment = e["assessment"]
                r: SearchResult = e["result"]
                lead = Lead(
                    campaign_id=campaign_id,
                    run_id=self.run_id,
                    company_name=a.company_name[:300],
                    website=(f"https://{e['domain']}" if e["domain"] else a.website)[:500],
                    domain=e["domain"][:300],
                    dedupe_key=e["dedupe_key"][:500],
                    contact_name=a.contact_name[:200],
                    contact_role=a.contact_role[:200],
                    linkedin_url=a.linkedin_url[:500],
                    email=e["email"][:320],
                    email_status=e["email_status"],
                    email_source=e["email_source"],
                    email_candidates=e["email_candidates"],
                    country=a.country[:100],
                    sector=a.sector[:100],
                    funding_stage=a.funding_stage[:100],
                    team_size=a.team_size[:50],
                    score=a.score,
                    fit_reason=a.fit_reason,
                    recommended_service=a.recommended_service[:200],
                    source_url=r.url[:1000],
                    source_snippet=r.snippet,
                )
                # Per-lead savepoint: the (campaign_id, dedupe_key) unique constraint
                # is the last-resort backstop behind self.seen_keys — a race should
                # never actually hit it, but if it does, skip just that one lead
                # instead of losing the whole batch's commit.
                try:
                    async with db.begin_nested():
                        db.add(lead)
                        await db.flush()
                except IntegrityError:
                    log.warning("run %s: duplicate lead skipped (dedupe_key=%s)",
                                self.run_id, e["dedupe_key"])
                    continue
                saved += 1
                if e["email"]:
                    self.stats["emails_found"] += 1
                if e["email_status"] == EmailStatus.verified:
                    self.stats["emails_verified"] += 1
            await db.commit()
        return saved

    # ------------------------------------------------------------------ #
    async def _update_run(self, iteration: int | None = None) -> None:
        async with SessionLocal() as db:
            run = await db.get(Run, self.run_id)
            if iteration is not None:
                run.iteration = iteration
            run.stats = dict(self.stats)
            await db.commit()

    async def _finish(self, status: RunStatus, error: str | None = None) -> None:
        async with SessionLocal() as db:
            run = await db.get(Run, self.run_id)
            run.status = status
            run.error = error
            run.stats = dict(self.stats)
            run.finished_at = _now()
            await db.commit()


def start_run_task(run_id: int) -> None:
    """Launch a run in the background and track it."""
    task = asyncio.create_task(AgentRun(run_id).execute(), name=f"leadgen-run-{run_id}")
    RUNNING_TASKS[run_id] = task
    task.add_done_callback(lambda _t: RUNNING_TASKS.pop(run_id, None))


def cancel_run_task(run_id: int) -> bool:
    task = RUNNING_TASKS.get(run_id)
    if task and not task.done():
        task.cancel()
        return True
    return False
