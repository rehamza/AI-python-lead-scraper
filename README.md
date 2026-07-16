# AI-Python-Lead-Scraper — AI Lead Generation Agent for B2B Sales

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-14%2B-336791?logo=postgresql&logoColor=white)](https://www.postgresql.org/)
[![Powered by Claude](https://img.shields.io/badge/Powered%20by-Claude-D97757)](https://www.anthropic.com/claude)

An **AI-powered B2B lead generation agent and Python web scraper** — a FastAPI backend that turns
a plain-language product/ICP description into an intent-qualified, email-verified lead list. An
AI agent (Claude) plans intelligent search queries, qualifies every result against your ideal
customer profile, discovers contact emails by crawling company websites, and verifies them —
all with **free-first infrastructure**, no paid search API required.

Campaign-driven by design: adding a new lead-gen use case is a single API call, not new code.

---

## Get started (no coding experience needed)

### Step 1 — Get the code

Click **Fork** (top-right of the [repo page](https://github.com/rehamza/AI-python-lead-scraper))
to make your own copy on GitHub — no git or coding experience needed for this step.

> While you're there: a ⭐ star helps other people find this tool. Found it useful? Share it —
> *"Found this AI lead-gen tool useful — https://github.com/rehamza/AI-python-lead-scraper"*
> works as a post on X, LinkedIn, or wherever your audience is.

Then, from **your fork's page** (`github.com/YOUR-USERNAME/AI-python-lead-scraper`):

**Don't know git?** Click the green **Code** button → **Download ZIP**, then unzip it anywhere on
your computer.

**Know git?**

```bash
git clone https://github.com/YOUR-USERNAME/AI-python-lead-scraper.git
cd AI-python-lead-scraper
```

### Step 2 — Run it

Open a terminal in that folder (Mac: right-click the folder → *New Terminal at Folder*;
Windows: Shift + right-click → *Open PowerShell window here*) and pick one path:

**Option A — Docker (recommended, easiest).** Installs and configures PostgreSQL for you — you
never touch a database.

1. Install [Docker Desktop](https://www.docker.com/products/docker-desktop/) if you don't have it.
2. In the project folder:
   ```bash
   cp .env.example .env
   ```
3. Open `.env` in any text editor and paste your [Anthropic API key](https://console.anthropic.com/)
   after `ANTHROPIC_API_KEY=`. Save the file.
4. Back in the terminal:
   ```bash
   docker compose up --build
   ```
5. Once it says the app started, open **http://localhost:8000/docs** in your browser.

**Option B — Manual (Python + your own PostgreSQL).** More control, more steps — see the full
[Quickstart](#quickstart) below.

### Step 3 — Use it without writing any code

Open **http://localhost:8000/docs** — this is an interactive control panel FastAPI generates
automatically. Click any endpoint to expand it, click **Try it out**, fill in the boxes, click
**Execute**. That's the whole interface: start a run, check progress, list leads, export a CSV —
all by clicking, no `curl` or coding required. (The `curl` commands elsewhere in this README are
just the same requests written as copy-pasteable text, for anyone who prefers a terminal.)

---

## Table of contents

- [Features](#features)
- [Architecture](#architecture)
- [Search providers](#search-providers--the-free-serper-answer)
- [Email verification](#email-verification-no-paid-apis)
- [How many leads it generates, and duplicate protection](#how-many-leads-it-generates-and-duplicate-protection)
- [Quickstart](#quickstart)
- [Usage](#usage)
- [Creating a new campaign](#creating-a-new-campaign-no-code-changes)
- [Keeping your real campaigns private](#keeping-your-real-campaigns-private)
- [Using this for your own business](#using-this-for-your-own-business)
- [Endpoints](#endpoints)
- [Project layout](#project-layout)
- [Cost & tuning notes](#cost--tuning-notes)
- [Contributing](#contributing)

## Features

- 🤖 **AI research agent** — Claude plans intent-signal search queries (funding announcements,
  hiring patterns, "looking for a dev partner" phrases), then scores and extracts structured
  data from every result against your ICP.
- 🔍 **Free-first search** — a provider chain (`ddg` → `searxng` → `brave` → `serper`) with
  automatic fallback and cooldown, so you're not locked into a paid SERP API.
- 📧 **Email discovery & verification** — crawls company sites for published emails, falls back
  to ranked pattern guesses, then verifies via MX lookup and an optional SMTP RCPT handshake with
  catch-all detection — no paid verification API.
- ⚙️ **Campaign-driven config** — every lead-gen use case (product, ICP, regions, positive/negative
  signals, target score) is a row, not a code change. Add a new one via `POST /api/campaigns`.
- 🎯 **Configurable lead count per run** — ask for 100, 500, 1000+ leads; the agent scales its
  effort automatically instead of stopping at a fixed default.
- 🧠 **Duplicate-safe** — persistent, per-campaign memory means reruns only ever add new leads.
- 🐘 **PostgreSQL-backed**, fully async (SQLAlchemy 2.0 + psycopg3).
- 📤 **CSV export** with score/email-confidence filters, ready for any outreach tool.

## Architecture

```
                        ┌─────────────────────────────────────────────┐
                        │                FastAPI (app/)               │
                        │  /api/campaigns  /api/runs  /api/leads      │
                        └────────────────────┬────────────────────────┘
                                             │ POST /campaigns/{id}/runs
                                             ▼
                 ┌────────────────── AI AGENT PIPELINE ──────────────────┐
                 │                (services/agent/pipeline.py)           │
                 │                                                       │
   feedback ┌────┤ 1. PLAN     Claude designs intent-signal queries      │
   loop     │    │ 2. SEARCH   provider chain (below)                    │
   (up to   │    │ 3. TRIAGE   dedupe vs DB, drop junk domains           │
   max_     │    │ 4. QUALIFY  Claude scores 0-100 + extracts structure  │
   iters)   │    │ 5. ENRICH   crawl company site for published emails   │
            │    │ 6. VERIFY   syntax → MX → SMTP RCPT + catch-all check │
            └───►│ 7. PERSIST  upsert into PostgreSQL                    │
                 └───────────────────────────────────────────────────────┘
                                             │
        ┌──────────────┬──────────────┬──────┴───────┐
        ▼              ▼              ▼              ▼
   ┌─────────┐    ┌─────────┐    ┌─────────┐    ┌─────────┐
   │  serper │ →  │   ddg   │ →  │ searxng │ →  │  brave  │   (auto-fallback chain,
   │  (paid) │    │  (FREE) │    │  (FREE, │    │  (free  │    order set in .env)
   └─────────┘    └─────────┘    │self-host│    │  tier)  │
                                 └─────────┘    └─────────┘
```

### Search providers — the "free Serper" answer

| Provider | Cost | Setup | Notes |
|---|---|---|---|
| `ddg` (ddgs lib) | **Free, no key** | none | Multi-engine metasearch (DuckDuckGo/Google/Bing HTML). Default free provider. Rate-limited politely by the app. |
| `searxng` | **Free, unlimited** | see below | Best free option at volume — your own metasearch server. Set `SEARXNG_URL`. |
| `brave` | Free tier (2k/mo) | API key | Clean API, good quality. |
| `serper` | Paid ($) | API key | Real Google SERP — highest accuracy. Used first when configured. |

The chain tries providers in `SEARCH_PROVIDER_ORDER`; unconfigured ones are skipped and a
provider that fails 3× goes into a 5-minute cooldown, so runs never stall.

**Running SearXNG locally:**

```bash
mkdir -p searxng
docker run -d --name searxng -p 8888:8080 \
  -v "$(pwd)/searxng:/etc/searxng" \
  -e "BASE_URL=http://localhost:8888/" \
  searxng/searxng:latest
```

First run generates `searxng/settings.yml` with just a secret key. JSON output (required by our
provider) is disabled by default for security — add it, then restart:

```yaml
use_default_settings: true
server:
  secret_key: "..."      # already generated, leave as-is
  image_proxy: true
  limiter: false          # the limiter blocks non-browser/JSON requests by default
search:
  formats:
    - html
    - json
```

```bash
docker restart searxng
curl "http://localhost:8888/search?q=test&format=json"   # should return JSON, not an error
```

Then set `SEARXNG_URL=http://localhost:8888` in `.env` — **unless** you're running the app itself
via `docker compose up` (see [Get started](#get-started-no-coding-experience-needed)), in which
case use `SEARXNG_URL=http://host.docker.internal:8888` instead, since the app runs in its own
container network and `localhost` there means "inside that container," not your machine.

### Email verification (no paid APIs)

1. **RFC syntax** (`email-validator`)
2. **MX lookup** (async dnspython, cached)
3. **SMTP RCPT handshake** on port 25 + **catch-all detection** (probes a random mailbox) — **off by default**
4. Statuses: `verified` > `accept_all` > `mx_valid` > `risky` (pattern guess) > `invalid` / `not_found`

> `SMTP_VERIFY_ENABLED=false` by default. The RCPT-TO handshake connects to each lead's mail
> server presenting `SMTP_HELO_DOMAIN`/`SMTP_FROM_ADDRESS` as its identity — done at volume under
> your real business domain, that probing pattern risks IP/domain reputation (some receiving
> servers flag it as harvesting, or attempt callback verification back to your domain). At the
> list-building stage MX-level confidence (`mx_valid`/`risky`) is enough. Enable full SMTP
> verification later, right before actual outreach — ideally via a dedicated bulk-verification
> service or a throwaway domain, not your primary one. (Also: most home/office ISPs block
> outbound port 25 anyway, so the verifier degrades to MX-only automatically if run locally.)
> Filter exports with `sendable_only=true` before any cold outreach either way.

## How many leads it generates, and duplicate protection

**Choosing a lead count.** Every campaign has a default (`target_leads_per_run`, e.g. 50), but
you can ask for a specific amount on any individual run — 100, 500, 1000, whatever you need —
without changing the campaign:

```bash
curl -X POST http://127.0.0.1:8000/api/campaigns/1/runs \
  -H 'Content-Type: application/json' \
  -d '{"target_leads": 500}'
```

(Or in the [interactive docs](#step-3--use-it-without-writing-any-code): expand `POST
/api/campaigns/{campaign_id}/runs`, *Try it out*, type `{"target_leads": 500}` in the request
body box, *Execute*.)

When you ask for more than the campaign's default, the agent automatically runs more
plan→search→qualify iterations to try to reach it — it doesn't just stop after the campaign's
usual 3 iterations because you asked for 20x the leads. There's a safety ceiling (25 iterations)
so a mistaken huge number can't run away with your API budget, and the run stops early if two
iterations in a row find zero new qualifying leads (the search space for that ICP is exhausted —
no point burning more LLM calls on it). Bigger asks cost more and take longer; see
[Cost & tuning notes](#cost--tuning-notes).

**No duplicates.** Every lead is saved with a dedupe key (company domain, or LinkedIn URL, or
name if neither is available). Before a run starts, it loads every dedupe key already saved for
that campaign from the database — this is the "memory": it's not in-process state that resets
when the server restarts, it's a persistent database record, so **rerunning the same campaign
next week only adds leads you don't already have**, however many runs happen in between.

## Quickstart

### Prerequisites

- Python 3.11+
- PostgreSQL 14+ (local install or Docker)
- An [Anthropic API key](https://console.anthropic.com/) — the agent's brain
- Docker (optional, only for self-hosting SearXNG, or if you use Option A below)

### Option A — Docker Compose (recommended)

Handles PostgreSQL for you — no local Python or Postgres install needed at all.

```bash
cp .env.example .env
# edit .env, paste your ANTHROPIC_API_KEY

docker compose up --build
```

That's it — open **http://127.0.0.1:8000/docs**. Data persists in a Docker volume across
restarts (`docker compose down` stops it, `docker compose up` brings it back with the same data;
`docker compose down -v` wipes the database volume too).

### Option B — Manual (Python + your own PostgreSQL)

#### 1. Clone and install

```bash
git clone https://github.com/rehamza/AI-python-lead-scraper.git
cd AI-python-lead-scraper

python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

#### 2. Database

Pick whichever Postgres you have — either works, the app only needs a connection string.

**Local PostgreSQL:**

```bash
createdb leadgen
```

**Or a single Docker container** (this is *not* the same as Option A above — this runs just
Postgres, and you still run the app yourself with uvicorn):

```bash
docker run -d --name leadgen-postgres \
  -e POSTGRES_USER=postgres -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=leadgen \
  -p 5432:5432 postgres:16
```

#### 3. Configure

```bash
cp .env.example .env
```

Edit `.env`:

| Variable | Required | Purpose |
|---|---|---|
| `DATABASE_URL` | ✅ | Point at whichever Postgres you set up above |
| `ANTHROPIC_API_KEY` | ✅ | The agent's LLM — [get one here](https://console.anthropic.com/) |
| `ANTHROPIC_MODEL` | — | Defaults to `claude-sonnet-5` (see [cost notes](#cost--tuning-notes)) |
| `SERPER_API_KEY` / `BRAVE_API_KEY` / `SEARXNG_URL` | — | Optional search providers — the free `ddg` provider works with none of these set |
| `SMTP_VERIFY_ENABLED` | — | Off by default — see [email verification](#email-verification-no-paid-apis) |

#### 4. Run

```bash
.venv/bin/uvicorn app.main:app --reload
```

Interactive API docs: **http://127.0.0.1:8000/docs**

On first boot the app creates tables and seeds one example campaign (`example-b2b-saas`) so
there's something to run immediately.

## Usage

```bash
# See campaigns (the "dynamic forms")
curl http://127.0.0.1:8000/api/campaigns

# Start an agent run for the example campaign (uses the campaign's default lead count)
curl -X POST http://127.0.0.1:8000/api/campaigns/1/runs

# ...or ask for a specific number of leads this run
curl -X POST http://127.0.0.1:8000/api/campaigns/1/runs -H 'Content-Type: application/json' -d '{"target_leads": 1000}'

# Watch progress (stats update live per iteration)
curl http://127.0.0.1:8000/api/runs/1

# Get the leads
curl "http://127.0.0.1:8000/api/leads?campaign_id=1&min_score=70&sendable_only=true"

# Export CSV for your outreach tool
curl -o leads.csv "http://127.0.0.1:8000/api/leads/export?campaign_id=1&sendable_only=true"

# Re-verify one lead's email later
curl -X POST http://127.0.0.1:8000/api/leads/42/verify

# Search-provider health
curl http://127.0.0.1:8000/api/providers
```

### Creating a new campaign (no code changes)

```bash
curl -X POST http://127.0.0.1:8000/api/campaigns -H 'Content-Type: application/json' -d '{
  "slug": "my-new-product",
  "name": "My New Product",
  "company_name": "Acme",
  "product_description": "What we sell...",
  "icp_description": "Who buys it, where, at what stage...",
  "regions": ["USA", "UK"],
  "sectors": ["B2B SaaS"],
  "positive_signals": ["just raised seed", "hiring designers not engineers"],
  "negative_signals": ["is a competitor"],
  "services": ["Thing A", "Thing B"],
  "min_score": 60,
  "target_leads_per_run": 50
}'
```

### Keeping your real campaigns private

The example campaign above is meant to be replaced. If you fork or self-host this repo for your
own business, put your real targeting strategy in `app/local_seed.py` instead of editing
`app/seed.py` directly:

```bash
cp app/local_seed.py.example app/local_seed.py
# edit app/local_seed.py with your real campaign(s)
```

`app/local_seed.py` is gitignored and loaded automatically on boot if present — your ICP
strategy, unannounced products, and scoring logic never end up in a public commit. See
`app/local_seed.py.example` for a few different campaign shapes (a blank template, an
MVP-development agency, a vertical SaaS) to model your own on.

## Using this for your own business

### Fork it

1. Click **Fork** (top-right of this repo's GitHub page) to get your own copy under your account.
2. Clone your fork:
   ```bash
   git clone https://github.com/YOUR-USERNAME/AI-python-lead-scraper.git
   cd AI-python-lead-scraper
   ```
3. Follow [Quickstart](#quickstart) to set up your own database and `.env`.
4. Add your real campaigns to `app/local_seed.py` (previous section) — they stay on your machine
   unless you choose to commit them.

> GitHub forks of a public repo are themselves public. If you want a fully private copy — e.g. to
> keep your customizations off GitHub entirely — clone this repo and push it into a **new private
> repository** of your own instead of using the Fork button. That gives you a private history
> rather than a linked public fork.

### Staying up to date

Watch this repo (bell icon, top-right) to get notified about new search providers, enrichment
sources, or fixes. Pull them into your fork whenever you want:

```bash
git remote add upstream https://github.com/rehamza/AI-python-lead-scraper.git
git fetch upstream
git merge upstream/main
```

### Found it useful?

Starring the repo is the single biggest thing that helps it reach more people — GitHub surfaces
starred and forked repos more in search and topic pages, which is how a tool like this gets found
at all. If you build a new search provider or enrichment source, a PR back benefits everyone
running it, not just you.

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | liveness |
| GET | `/api/providers` | search-provider chain status |
| POST/GET | `/api/campaigns` | create / list campaigns |
| GET/PATCH/DELETE | `/api/campaigns/{id}` | manage one campaign |
| POST | `/api/campaigns/{id}/runs` | **start an agent run** — optional body `{"target_leads": N}` (202, runs in background) |
| GET | `/api/runs`, `/api/runs/{id}` | run status + live stats (includes `target_leads` if set) |
| POST | `/api/runs/{id}/cancel` | cancel a running agent |
| GET | `/api/leads` | filter: `campaign_id, run_id, min_score, email_status, sendable_only, search, limit, offset` |
| GET | `/api/leads/export` | CSV download (same filters) |
| POST | `/api/leads/{id}/verify` | re-run email verification |

## Project layout

```
app/
├── main.py                    FastAPI app, lifespan (create tables + seed)
├── config.py                  .env settings
├── database.py                async SQLAlchemy engine/session
├── models.py                  Campaign / Run / Lead ORM
├── schemas.py                 API schemas + LLM structured-output schemas
├── seed.py                    generic example campaign + local_seed.py loader
├── local_seed.py.example      template for your own private campaigns
├── api/                       campaigns, runs, leads, providers routers
└── services/
    ├── llm.py                 Claude wrapper (messages.parse structured outputs)
    ├── agent/
    │   ├── pipeline.py        the 7-stage agent loop
    │   └── prompts.py         planner + qualifier prompts
    ├── search/                base, ddg, serper, searxng, brave, chain
    └── enrichment/
        ├── crawler.py         async site crawl for published emails
        └── verifier.py        MX + SMTP + catch-all verification

Dockerfile, docker-compose.yml   one-command setup (app + PostgreSQL)
```

## Cost & tuning notes

- **LLM**: default model is `claude-sonnet-5` — the query-planning and qualification tasks are
  structured (scoring against explicit rubrics), so Sonnet is the cost/quality sweet spot here.
  Set `ANTHROPIC_MODEL=claude-opus-4-8` in `.env` if you want Opus-level judgment on ambiguous
  ICPs, or `claude-haiku-4-5` to cut cost further (spot-check qualification accuracy first —
  cheaper models are more likely to let weak leads through).
- A run makes ~`iterations × (1 planner call + ceil(results/batch_size) qualifier calls)`.
  Defaults: 3 iterations × 12 queries × 10 results ⇒ ~37 LLM calls worst case. Asking for a much
  larger `target_leads` scales the iteration count (and therefore cost) up proportionally, capped
  at 25 iterations — see [How many leads it generates](#how-many-leads-it-generates-and-duplicate-protection).
- **Search volume**: with only free `ddg`, keep `queries_per_iteration ≤ 15` to stay under the
  radar; for scale, self-host SearXNG (unlimited) or add Serper credits.
- Single-process by design (background runs use `asyncio.Task`). If you later need multiple
  workers or durability across restarts, swap `start_run_task` for a queue (arq / Celery).

## Contributing

Issues and PRs welcome — this started as an internal tool and is shared as-is for anyone who
needs an AI-driven lead scraper without paying for a SERP API. Fork it, adapt the campaign shape
to your own product, and open a PR if you build a search provider or enrichment source worth
sharing back.

## License

[MIT](LICENSE) — do whatever you want with it.
