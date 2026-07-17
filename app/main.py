"""LeadForge — AI-powered B2B lead generation backend.

Run with:
    uvicorn app.main:app --reload
"""
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI
from sqlalchemy import update

from app.api import campaigns, leads, providers, runs
from app.database import SessionLocal, engine, init_db
from app.models import Run, RunStatus
from app.seed import seed_campaigns

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("leadforge")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    async with SessionLocal() as db:
        created = await seed_campaigns(db)
        if created:
            log.info("seeded %d default campaign(s)", created)
        # Runs execute as in-process asyncio tasks, so any run still marked
        # queued/running at boot was killed by a restart and will never resume —
        # mark it failed so it doesn't show as "running" forever.
        orphaned = await db.execute(
            update(Run)
            .where(Run.status.in_([RunStatus.queued, RunStatus.running]))
            .values(
                status=RunStatus.failed,
                error="Interrupted by server restart",
                finished_at=datetime.now(timezone.utc),
            )
        )
        await db.commit()
        if orphaned.rowcount:
            log.info("marked %d orphaned run(s) as failed after restart", orphaned.rowcount)
    yield
    await engine.dispose()


app = FastAPI(
    title="LeadForge",
    description=(
        "AI lead-generation backend: campaign-driven agent that plans searches, "
        "qualifies leads with Claude, finds emails, and verifies them — free-first "
        "search providers with Serper as premium fallback."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(campaigns.router)
app.include_router(runs.router)
app.include_router(leads.router)
app.include_router(providers.router)


@app.get("/health", tags=["meta"])
async def health():
    return {"status": "ok"}
