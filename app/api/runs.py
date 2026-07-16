"""Run lifecycle: start an agent run, watch progress, cancel."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Campaign, Run, RunStatus
from app.schemas import RunOut
from app.services.agent.pipeline import cancel_run_task, start_run_task

router = APIRouter(prefix="/api", tags=["runs"])


@router.post("/campaigns/{campaign_id}/runs", response_model=RunOut, status_code=202)
async def start_run(campaign_id: int, db: AsyncSession = Depends(get_db)):
    campaign = await db.get(Campaign, campaign_id)
    if not campaign:
        raise HTTPException(404, "Campaign not found")
    if not campaign.active:
        raise HTTPException(409, "Campaign is inactive")

    active = await db.execute(
        select(Run.id).where(
            Run.campaign_id == campaign_id,
            Run.status.in_([RunStatus.queued, RunStatus.running]),
        )
    )
    if active.first() is not None:
        raise HTTPException(409, "A run is already in progress for this campaign")

    run = Run(campaign_id=campaign_id, status=RunStatus.queued)
    db.add(run)
    await db.commit()
    await db.refresh(run)

    start_run_task(run.id)
    return run


@router.get("/runs", response_model=list[RunOut])
async def list_runs(campaign_id: int | None = None, db: AsyncSession = Depends(get_db)):
    query = select(Run).order_by(Run.id.desc()).limit(100)
    if campaign_id is not None:
        query = query.where(Run.campaign_id == campaign_id)
    result = await db.execute(query)
    return result.scalars().all()


@router.get("/runs/{run_id}", response_model=RunOut)
async def get_run(run_id: int, db: AsyncSession = Depends(get_db)):
    run = await db.get(Run, run_id)
    if not run:
        raise HTTPException(404, "Run not found")
    return run


@router.post("/runs/{run_id}/cancel", response_model=RunOut)
async def cancel_run(run_id: int, db: AsyncSession = Depends(get_db)):
    run = await db.get(Run, run_id)
    if not run:
        raise HTTPException(404, "Run not found")
    if run.status not in (RunStatus.queued, RunStatus.running):
        raise HTTPException(409, f"Run is {run.status.value}; nothing to cancel")
    cancel_run_task(run_id)
    await db.refresh(run)
    return run
