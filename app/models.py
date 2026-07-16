"""SQLAlchemy ORM models: Campaign, Run, Lead."""
import enum
from datetime import datetime

from sqlalchemy import (
    JSON,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class RunStatus(str, enum.Enum):
    queued = "queued"
    running = "running"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


class EmailStatus(str, enum.Enum):
    verified = "verified"        # SMTP confirmed the mailbox exists
    accept_all = "accept_all"    # domain accepts anything — deliverable but unproven
    mx_valid = "mx_valid"        # domain can receive mail; mailbox unconfirmed
    risky = "risky"              # pattern guess, MX ok
    invalid = "invalid"          # syntax/MX/SMTP failure — do not send
    not_found = "not_found"      # no email discovered


class Campaign(Base):
    """A reusable lead-gen configuration (the 'dynamic form').

    Everything the agent needs to know about a product/ICP lives here, so new
    use cases (Softquorra services, Socialope, future products) are just rows.
    """

    __tablename__ = "campaigns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))

    company_name: Mapped[str] = mapped_column(String(200))
    company_url: Mapped[str] = mapped_column(String(500), default="")
    product_description: Mapped[str] = mapped_column(Text)
    icp_description: Mapped[str] = mapped_column(Text)

    regions: Mapped[list] = mapped_column(JSON, default=list)
    sectors: Mapped[list] = mapped_column(JSON, default=list)
    positive_signals: Mapped[list] = mapped_column(JSON, default=list)
    negative_signals: Mapped[list] = mapped_column(JSON, default=list)
    services: Mapped[list] = mapped_column(JSON, default=list)

    min_score: Mapped[int] = mapped_column(Integer, default=60)
    target_leads_per_run: Mapped[int] = mapped_column(Integer, default=50)
    max_iterations: Mapped[int] = mapped_column(Integer, default=3)
    queries_per_iteration: Mapped[int] = mapped_column(Integer, default=12)
    results_per_query: Mapped[int] = mapped_column(Integer, default=10)

    active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    runs: Mapped[list["Run"]] = relationship(back_populates="campaign", cascade="all, delete-orphan")
    leads: Mapped[list["Lead"]] = relationship(back_populates="campaign", cascade="all, delete-orphan")

    def agent_brief(self) -> dict:
        """The campaign as a dict handed to the LLM agent."""
        return {
            "company": {"name": self.company_name, "url": self.company_url},
            "product_description": self.product_description,
            "ideal_customer_profile": self.icp_description,
            "target_regions": self.regions,
            "target_sectors": self.sectors,
            "positive_signals": self.positive_signals,
            "negative_signals": self.negative_signals,
            "services_offered": self.services,
        }


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("campaigns.id", ondelete="CASCADE"), index=True)
    status: Mapped[RunStatus] = mapped_column(Enum(RunStatus), default=RunStatus.queued, index=True)
    iteration: Mapped[int] = mapped_column(Integer, default=0)
    stats: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    campaign: Mapped[Campaign] = relationship(back_populates="runs")
    leads: Mapped[list["Lead"]] = relationship(back_populates="run")


class Lead(Base):
    __tablename__ = "leads"
    __table_args__ = (UniqueConstraint("campaign_id", "dedupe_key", name="uq_lead_campaign_dedupe"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("campaigns.id", ondelete="CASCADE"), index=True)
    run_id: Mapped[int | None] = mapped_column(ForeignKey("runs.id", ondelete="SET NULL"), nullable=True)

    company_name: Mapped[str] = mapped_column(String(300), default="")
    website: Mapped[str] = mapped_column(String(500), default="")
    domain: Mapped[str] = mapped_column(String(300), default="", index=True)
    dedupe_key: Mapped[str] = mapped_column(String(500))

    contact_name: Mapped[str] = mapped_column(String(200), default="")
    contact_role: Mapped[str] = mapped_column(String(200), default="")
    linkedin_url: Mapped[str] = mapped_column(String(500), default="")

    email: Mapped[str] = mapped_column(String(320), default="", index=True)
    email_status: Mapped[EmailStatus] = mapped_column(Enum(EmailStatus), default=EmailStatus.not_found, index=True)
    email_source: Mapped[str] = mapped_column(String(50), default="")  # website|search|pattern
    email_candidates: Mapped[list] = mapped_column(JSON, default=list)

    country: Mapped[str] = mapped_column(String(100), default="")
    sector: Mapped[str] = mapped_column(String(100), default="")
    funding_stage: Mapped[str] = mapped_column(String(100), default="")
    team_size: Mapped[str] = mapped_column(String(50), default="")

    score: Mapped[float] = mapped_column(Float, default=0, index=True)
    fit_reason: Mapped[str] = mapped_column(Text, default="")
    recommended_service: Mapped[str] = mapped_column(String(200), default="")

    source_url: Mapped[str] = mapped_column(String(1000), default="")
    source_snippet: Mapped[str] = mapped_column(Text, default="")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    campaign: Mapped[Campaign] = relationship(back_populates="leads")
    run: Mapped[Run | None] = relationship(back_populates="leads")
