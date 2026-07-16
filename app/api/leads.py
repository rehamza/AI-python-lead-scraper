"""Lead listing, CSV export, and email re-verification."""
import csv
import io

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import EmailStatus, Lead
from app.schemas import LeadOut
from app.services.enrichment.verifier import verify_email

router = APIRouter(prefix="/api/leads", tags=["leads"])

_EXPORT_COLUMNS = [
    "id", "company_name", "website", "contact_name", "contact_role", "email",
    "email_status", "email_source", "linkedin_url", "country", "sector",
    "funding_stage", "team_size", "score", "fit_reason", "recommended_service",
    "source_url", "created_at",
]


def _leads_query(
    campaign_id: int | None,
    run_id: int | None,
    min_score: float | None,
    email_status: EmailStatus | None,
    sendable_only: bool,
    search: str | None,
):
    query = select(Lead).order_by(Lead.score.desc(), Lead.id.desc())
    if campaign_id is not None:
        query = query.where(Lead.campaign_id == campaign_id)
    if run_id is not None:
        query = query.where(Lead.run_id == run_id)
    if min_score is not None:
        query = query.where(Lead.score >= min_score)
    if email_status is not None:
        query = query.where(Lead.email_status == email_status)
    if sendable_only:
        query = query.where(
            Lead.email_status.in_([EmailStatus.verified, EmailStatus.accept_all, EmailStatus.mx_valid])
        )
    if search:
        pattern = f"%{search}%"
        query = query.where(
            or_(Lead.company_name.ilike(pattern), Lead.domain.ilike(pattern), Lead.contact_name.ilike(pattern))
        )
    return query


@router.get("", response_model=list[LeadOut])
async def list_leads(
    campaign_id: int | None = None,
    run_id: int | None = None,
    min_score: float | None = None,
    email_status: EmailStatus | None = None,
    sendable_only: bool = False,
    search: str | None = None,
    limit: int = 100,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
):
    query = _leads_query(campaign_id, run_id, min_score, email_status, sendable_only, search)
    result = await db.execute(query.limit(min(limit, 500)).offset(offset))
    return result.scalars().all()


@router.get("/export")
async def export_leads_csv(
    campaign_id: int | None = None,
    run_id: int | None = None,
    min_score: float | None = None,
    email_status: EmailStatus | None = None,
    sendable_only: bool = False,
    db: AsyncSession = Depends(get_db),
):
    query = _leads_query(campaign_id, run_id, min_score, email_status, sendable_only, None)
    result = await db.execute(query)
    leads = result.scalars().all()

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(_EXPORT_COLUMNS)
    for lead in leads:
        writer.writerow([
            lead.id, lead.company_name, lead.website, lead.contact_name, lead.contact_role,
            lead.email, lead.email_status.value, lead.email_source, lead.linkedin_url,
            lead.country, lead.sector, lead.funding_stage, lead.team_size, lead.score,
            lead.fit_reason, lead.recommended_service, lead.source_url,
            lead.created_at.isoformat() if lead.created_at else "",
        ])
    buffer.seek(0)
    filename = f"leads_campaign_{campaign_id or 'all'}.csv"
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/{lead_id}/verify", response_model=LeadOut)
async def reverify_lead_email(lead_id: int, db: AsyncSession = Depends(get_db)):
    lead = await db.get(Lead, lead_id)
    if not lead:
        raise HTTPException(404, "Lead not found")
    if not lead.email:
        raise HTTPException(409, "Lead has no email to verify")
    lead.email_status = await verify_email(lead.email, is_guess=lead.email_source == "pattern")
    await db.commit()
    await db.refresh(lead)
    return lead
