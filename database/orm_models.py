from __future__ import annotations

"""SQLAlchemy ORM models for the platform database tables.

Purpose:
- Defines typed ORM mappings for the core lead-generation tables so services can
  perform database operations without raw SQL text queries.

Dependencies:
- SQLAlchemy declarative ORM.
- PostgreSQL UUID column support.

Usage:
- Import mapped classes in services that need ORM-backed reads/writes, for
  example `from database.orm_models import Company, LeadScore`.
"""

from datetime import date, datetime
import uuid
from typing import TYPE_CHECKING, Any, Generic, TypeVar

from sqlalchemy import Boolean, Column, Date, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import declarative_base

ModelT = TypeVar("ModelT")

if TYPE_CHECKING:
    from sqlalchemy.orm import Mapped
else:
    class Mapped(Generic[ModelT]):
        """Compatibility placeholder used when annotations are evaluated at runtime."""

try:
    from sqlalchemy.orm import DeclarativeBase, mapped_column

    class Base(DeclarativeBase):
        """Base class for all ORM models."""

except ImportError:
    def mapped_column(*args: Any, **kwargs: Any) -> Any:
        """Fallback to Column() for SQLAlchemy 1.4 compatibility."""
        return Column(*args, **kwargs)

    Base = declarative_base()


class AgentRun(Base):
    """ORM mapping for the agent_runs table.

    One row per pipeline run, whether triggered from chat or Airflow.
    Tracks target context, current stage, status, output counters, and errors.
    """

    __tablename__ = "agent_runs"

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    trigger_source: Mapped[str] = mapped_column(String(50), nullable=False)
    trigger_input: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    target_industry: Mapped[str | None] = mapped_column(String(100), nullable=True)
    target_location: Mapped[str | None] = mapped_column(String(200), nullable=True)
    target_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="started")
    current_stage: Mapped[str | None] = mapped_column(String(50), nullable=True)
    companies_found: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    companies_scored: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    companies_approved: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    drafts_created: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    emails_sent: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_retries: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class AgentRunLog(Base):
    """ORM mapping for the agent_run_logs table.

    Step-by-step audit of every action inside a run.
    Every agent writes one row per action: source tried, quality checked, email sent, etc.
    """

    __tablename__ = "agent_run_logs"

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("agent_runs.id"), nullable=False)
    agent: Mapped[str] = mapped_column(String(50), nullable=False)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    input_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    output_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    quality_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    logged_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class SourcePerformance(Base):
    """ORM mapping for the source_performance table.

    Learning memory for Scout agent.
    Tracks how well each source performs per industry+location combination.
    Scout reads this at run start to rank sources and try the best one first.
    """

    __tablename__ = "source_performance"

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_name: Mapped[str] = mapped_column(String(200), nullable=False)
    industry: Mapped[str] = mapped_column(String(100), nullable=False)
    location: Mapped[str] = mapped_column(String(200), nullable=False)
    total_runs: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_leads_found: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_leads_passed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    avg_quality_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    last_quality_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class EmailWinRate(Base):
    """ORM mapping for the email_win_rate table.

    Learning memory for Writer agent.
    Tracks open/reply rates per template+industry combination.
    Writer reads this to pick the best-performing template next time.
    """

    __tablename__ = "email_win_rate"

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    template_id: Mapped[str] = mapped_column(String(100), nullable=False)
    industry: Mapped[str] = mapped_column(String(100), nullable=False)
    emails_sent: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    emails_opened: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    replies_received: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    positive_replies: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    open_rate: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    reply_rate: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    positive_reply_rate: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class HumanApprovalRequest(Base):
    """ORM mapping for the human_approval_requests table.

    Tracks pending human-in-the-loop approval steps.
    Created when Analyst finishes scoring or Writer finishes drafts.
    System sends an email notification. Pipeline pauses until approved.
    """

    __tablename__ = "human_approval_requests"

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("agent_runs.id"), nullable=True)
    approval_type: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending")
    items_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    items_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    notification_email: Mapped[str | None] = mapped_column(String(200), nullable=True)
    notification_sent: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    notification_sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    approved_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class Company(Base):
    """ORM mapping for the companies table."""

    __tablename__ = "companies"

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    website: Mapped[str | None] = mapped_column(String(500), nullable=True)
    industry: Mapped[str | None] = mapped_column(String(100), nullable=True)
    sub_industry: Mapped[str | None] = mapped_column(String(100), nullable=True)
    city: Mapped[str | None] = mapped_column(String(100), nullable=True)
    state: Mapped[str | None] = mapped_column(String(50), nullable=True)
    employee_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    site_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    phone: Mapped[str | None] = mapped_column(String(30), nullable=True)
    source: Mapped[str | None] = mapped_column(String(200), nullable=True)
    source_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    date_found: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str | None] = mapped_column(String(50), nullable=True)
    run_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("agent_runs.id"), nullable=True)
    quality_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    intent_signal: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class DirectorySource(Base):
    """ORM mapping for reusable scout directory source URLs."""

    __tablename__ = "directory_sources"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    url: Mapped[str] = mapped_column(String(1000), nullable=False)
    category: Mapped[str | None] = mapped_column(String(100), nullable=True)
    location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    pagination: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    discovered_via: Mapped[str | None] = mapped_column(String(50), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class CompanyFeature(Base):
    """ORM mapping for the company_features table."""

    __tablename__ = "company_features"

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    company_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("companies.id"),
        nullable=True,
    )
    estimated_sqft_per_site: Mapped[float | None] = mapped_column(Float, nullable=True)
    estimated_site_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    estimated_annual_utility_spend: Mapped[float | None] = mapped_column(Float, nullable=True)
    estimated_annual_telecom_spend: Mapped[float | None] = mapped_column(Float, nullable=True)
    estimated_total_spend: Mapped[float | None] = mapped_column(Float, nullable=True)
    savings_low: Mapped[float | None] = mapped_column(Float, nullable=True)
    savings_mid: Mapped[float | None] = mapped_column(Float, nullable=True)
    savings_high: Mapped[float | None] = mapped_column(Float, nullable=True)
    industry_fit_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    multi_site_confirmed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    deregulated_state: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    data_quality_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    computed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class LeadScore(Base):
    """ORM mapping for the lead_scores table."""

    __tablename__ = "lead_scores"

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    company_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("companies.id"),
        nullable=True,
    )
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    tier: Mapped[str | None] = mapped_column(String(20), nullable=True)
    score_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    approved_human: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    approved_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    scored_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Contact(Base):
    """ORM mapping for the contacts table."""

    __tablename__ = "contacts"

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    company_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("companies.id"),
        nullable=True,
    )
    full_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    email: Mapped[str | None] = mapped_column(String(200), nullable=True)
    linkedin_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    source: Mapped[str | None] = mapped_column(String(100), nullable=True)
    verified: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    unsubscribed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class EmailDraft(Base):
    """ORM mapping for the email_drafts table."""

    __tablename__ = "email_drafts"

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    company_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("companies.id"),
        nullable=True,
    )
    contact_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("contacts.id"),
        nullable=True,
    )
    subject_line: Mapped[str | None] = mapped_column(String(300), nullable=True)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    savings_estimate: Mapped[str | None] = mapped_column(String(100), nullable=True)
    template_used: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    approved_human: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    approved_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    edited_human: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    critic_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    low_confidence: Mapped[bool | None] = mapped_column(Boolean, nullable=True, default=False)
    rewrite_count: Mapped[int | None] = mapped_column(Integer, nullable=True, default=0)


class OutreachEvent(Base):
    """ORM mapping for the outreach_events table."""

    __tablename__ = "outreach_events"

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    company_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("companies.id"),
        nullable=True,
    )
    contact_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("contacts.id"),
        nullable=True,
    )
    email_draft_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("email_drafts.id"),
        nullable=True,
    )
    event_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    event_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    reply_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    reply_sentiment: Mapped[str | None] = mapped_column(String(20), nullable=True)
    follow_up_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    next_followup_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    sales_alerted: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    alerted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)