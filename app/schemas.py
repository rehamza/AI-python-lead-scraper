"""Pydantic schemas for API I/O and LLM structured outputs."""
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models import EmailStatus, RunStatus

# ---------------------------------------------------------------------------
# Campaign API schemas
# ---------------------------------------------------------------------------


class CampaignBase(BaseModel):
    name: str
    slug: str = Field(pattern=r"^[a-z0-9-]+$", max_length=80)
    company_name: str
    company_url: str = ""
    product_description: str
    icp_description: str
    regions: list[str] = []
    sectors: list[str] = []
    positive_signals: list[str] = []
    negative_signals: list[str] = []
    services: list[str] = []
    min_score: int = Field(default=60, ge=0, le=100)
    target_leads_per_run: int = Field(default=50, ge=1, le=1000)
    max_iterations: int = Field(default=3, ge=1, le=10)
    queries_per_iteration: int = Field(default=12, ge=1, le=50)
    results_per_query: int = Field(default=10, ge=5, le=50)
    active: bool = True


class CampaignCreate(CampaignBase):
    pass


class CampaignUpdate(BaseModel):
    name: str | None = None
    company_name: str | None = None
    company_url: str | None = None
    product_description: str | None = None
    icp_description: str | None = None
    regions: list[str] | None = None
    sectors: list[str] | None = None
    positive_signals: list[str] | None = None
    negative_signals: list[str] | None = None
    services: list[str] | None = None
    min_score: int | None = Field(default=None, ge=0, le=100)
    target_leads_per_run: int | None = Field(default=None, ge=1, le=1000)
    max_iterations: int | None = Field(default=None, ge=1, le=10)
    queries_per_iteration: int | None = Field(default=None, ge=1, le=50)
    results_per_query: int | None = Field(default=None, ge=5, le=50)
    active: bool | None = None


class CampaignOut(CampaignBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Run API schemas
# ---------------------------------------------------------------------------


class RunCreate(BaseModel):
    """Optional body for POST /campaigns/{id}/runs. Omit to use campaign defaults."""

    target_leads: int | None = Field(
        default=None, ge=1, le=5000,
        description="How many leads to generate this run, e.g. 100 / 500 / 1000. "
                    "Overrides the campaign's target_leads_per_run for this run only.",
    )


class RunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    campaign_id: int
    status: RunStatus
    iteration: int
    target_leads: int | None
    stats: dict
    error: str | None
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime


# ---------------------------------------------------------------------------
# Lead API schemas
# ---------------------------------------------------------------------------


class LeadOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    campaign_id: int
    run_id: int | None
    company_name: str
    website: str
    domain: str
    contact_name: str
    contact_role: str
    linkedin_url: str
    email: str
    email_status: EmailStatus
    email_source: str
    email_candidates: list
    country: str
    sector: str
    funding_stage: str
    team_size: str
    score: float
    fit_reason: str
    recommended_service: str
    source_url: str
    created_at: datetime


# ---------------------------------------------------------------------------
# LLM structured-output schemas (used with client.messages.parse)
#
# IMPORTANT: every field here must be REQUIRED (no defaults). The structured-
# outputs API compiles the schema into a grammar server-side, and each
# optional field counts against a hard complexity budget — a schema with many
# optional fields is rejected with 400 "Schema is too complex" or "Grammar
# compilation timed out". Required fields cost nothing: the grammar simply
# forces the model to emit every field, using "" / 0 for unknowns.
# Numeric bounds (ge/le) are also unsupported on the wire — express ranges in
# the description and clamp in code instead.
# ---------------------------------------------------------------------------


class PlannedQuery(BaseModel):
    query: str = Field(description="A ready-to-run web search query / dork")
    region: str = Field(description='Region this query targets, or "" if global')
    intent: str = Field(description='What kind of lead this query is designed to surface, or ""')


class QueryPlan(BaseModel):
    queries: list[PlannedQuery]


class LeadAssessment(BaseModel):
    result_index: int = Field(description="Index of the search result this assessment refers to")
    is_lead: bool = Field(description="True only if this is a genuine potential customer for the campaign")
    score: int = Field(description="Fit score, an integer from 0 to 100")
    company_name: str = Field(description='Company name, or "" if not identifiable')
    website: str = Field(description='Company website URL if identifiable, else ""')
    contact_name: str = Field(description='Founder/decision-maker full name if present, else ""')
    contact_role: str = Field(description='Contact role/title, or ""')
    linkedin_url: str = Field(description='LinkedIn URL if present, else ""')
    country: str = Field(description='Country, or ""')
    sector: str = Field(description='Sector/industry, or ""')
    funding_stage: str = Field(description='Funding stage if known, else ""')
    team_size: str = Field(description='Team size if known, else ""')
    fit_reason: str = Field(description="1-2 sentences: why they would buy / outsource")
    recommended_service: str = Field(description='Which of the campaign\'s services fits best, or ""')


class QualifiedBatch(BaseModel):
    assessments: list[LeadAssessment]
