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

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Base class for all ORM models."""


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
    source: Mapped[str | None] = mapped_column(String(200), nullable=True)
    source_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    date_found: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str | None] = mapped_column(String(50), nullable=True)
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