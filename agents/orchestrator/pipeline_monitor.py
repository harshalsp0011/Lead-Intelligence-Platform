from __future__ import annotations

"""Pipeline health and activity monitor.

Purpose:
- Provides pipeline status counts, value rollups, service health checks,
  stuck-condition detection, and recent outreach activity snapshots.

Dependencies:
- `sqlalchemy` session for queries across companies, scoring, features,
  drafts, and outreach events.
- `requests` for service health endpoint checks.
- `config.settings.get_settings` for API keys and contingency fee settings.
- `database.connection.check_connection` for PostgreSQL health probe.

Usage:
- Call these functions from dashboards, scheduled checks, or admin endpoints.
"""

from datetime import datetime, timedelta, timezone
from typing import Any

import requests
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from config.settings import get_settings
from database.connection import check_connection
from database.orm_models import Company, CompanyFeature, Contact, EmailDraft, LeadScore, OutreachEvent

_EXPECTED_STATUSES = [
    "new",
    "enriched",
    "scored",
    "approved",
    "contacted",
    "replied",
    "meeting_booked",
    "won",
    "lost",
    "no_response",
    "archived",
]


def get_pipeline_counts(db_session: Session) -> dict[str, int]:
    """Return count of companies grouped by status with zero-filled defaults."""
    all_statuses: list[str | None] = list(db_session.execute(
        select(Company.status)
    ).scalars().all())

    counts: dict[str, int] = {status: 0 for status in _EXPECTED_STATUSES}
    for raw in all_statuses:
        key = (raw or "new").strip().lower()
        if key in counts:
            counts[key] += 1

    return counts


def get_pipeline_value(db_session: Session) -> dict[str, Any]:
    """Return high-tier pipeline savings totals and estimated TB revenue."""
    _excluded = ["lost", "archived", "no_response"]
    active_companies: list[Company] = list(db_session.execute(
        select(Company).where(Company.status.not_in(_excluded))
    ).scalars().all())

    total_leads_high = 0
    total_savings_low = 0.0
    total_savings_mid = 0.0
    total_savings_high = 0.0

    for company in active_companies:
        latest_score: LeadScore | None = db_session.execute(
            select(LeadScore)
            .where(LeadScore.company_id == company.id)
            .order_by(LeadScore.scored_at.desc())
            .limit(1)
        ).scalar()
        if not latest_score or latest_score.tier != "high":
            continue

        total_leads_high += 1
        latest_feature: CompanyFeature | None = db_session.execute(
            select(CompanyFeature)
            .where(CompanyFeature.company_id == company.id)
            .order_by(CompanyFeature.computed_at.desc())
            .limit(1)
        ).scalar()
        if latest_feature:
            total_savings_low += float(latest_feature.savings_low or 0.0)
            total_savings_mid += float(latest_feature.savings_mid or 0.0)
            total_savings_high += float(latest_feature.savings_high or 0.0)

    contingency_fee = float(getattr(get_settings(), "TB_CONTINGENCY_FEE", 0.24) or 0.24)
    total_tb_revenue_est = total_savings_mid * contingency_fee

    return {
        "total_leads_high": total_leads_high,
        "total_savings_low": total_savings_low,
        "total_savings_mid": total_savings_mid,
        "total_savings_high": total_savings_high,
        "total_tb_revenue_est": total_tb_revenue_est,
    }


def check_agent_health() -> dict[str, dict[str, str]]:
    """Return health status for core services and critical credentials."""
    settings = get_settings()
    ollama_url = str(getattr(settings, "OLLAMA_BASE_URL", "http://host.docker.internal:11434") or "http://host.docker.internal:11434").rstrip("/")

    health: dict[str, dict[str, str]] = {
        "postgres": _ok("Postgres reachable") if check_connection() else _error("Postgres connection failed"),
        "ollama": _probe_url(ollama_url),
        "api": _probe_url("http://localhost:8001/health"),
        "airflow": _probe_url("http://host.docker.internal:8080/health"),
        "sendgrid": _ok("SENDGRID_API_KEY configured") if settings.SENDGRID_API_KEY else _warning("SENDGRID_API_KEY missing"),
        "tavily": _ok("TAVILY_API_KEY configured") if settings.TAVILY_API_KEY else _warning("TAVILY_API_KEY missing"),
        "slack": _ok("SLACK_WEBHOOK_URL configured") if settings.SLACK_WEBHOOK_URL else _warning("SLACK_WEBHOOK_URL missing"),
    }

    return health


def detect_stuck_pipeline(db_session: Session) -> list[str]:
    """Return human-readable issue strings for stalled pipeline conditions."""
    issues: list[str] = []

    cutoff_24h = datetime.now(timezone.utc) - timedelta(hours=24)
    new_count = int(db_session.execute(
        select(func.count(Company.id)).where(
            (Company.status.is_(None)) | (Company.status == "new"),
            Company.created_at < cutoff_24h,
        )
    ).scalar_one() or 0)
    if new_count > 0:
        issues.append(f"{new_count} companies found but not yet analyzed")

    cutoff_48h = datetime.now(timezone.utc) - timedelta(hours=48)
    high_waiting_count = int(db_session.execute(
        select(func.count(LeadScore.id))
        .join(Company, Company.id == LeadScore.company_id)
        .where(
            Company.status == "scored",
            LeadScore.tier == "high",
            (LeadScore.approved_human == False) | (LeadScore.approved_human.is_(None)),  # noqa: E712
            LeadScore.scored_at < cutoff_48h,
        )
    ).scalar_one() or 0)
    if high_waiting_count > 0:
        issues.append(f"{high_waiting_count} high-score leads waiting approval")

    cutoff_6h = datetime.now(timezone.utc) - timedelta(hours=6)
    approved_drafts = db_session.execute(
        select(EmailDraft.id).where(
            EmailDraft.approved_human == True,  # noqa: E712
            EmailDraft.created_at < cutoff_6h,
        )
    ).scalars().all()
    approved_unsent_count = 0
    for draft_id in approved_drafts:
        sent_exists = db_session.execute(
            select(OutreachEvent.id).where(
                OutreachEvent.email_draft_id == draft_id,
                OutreachEvent.event_type.in_(["sent", "followup_sent"]),
            ).limit(1)
        ).scalar()
        if sent_exists is None:
            approved_unsent_count += 1
    if approved_unsent_count > 0:
        issues.append(f"{approved_unsent_count} approved emails not yet sent")

    is_weekday = datetime.now(timezone.utc).isoweekday() in {1, 2, 3, 4, 5}
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    sent_today = int(db_session.execute(
        select(func.count(OutreachEvent.id)).where(
            OutreachEvent.event_type == "sent",
            OutreachEvent.event_at >= today_start,
        )
    ).scalar_one() or 0)

    if is_weekday and sent_today == 0:
        issues.append("No emails sent today — check outreach agent")

    return issues


def get_recent_activity(db_session: Session, limit: int = 10) -> list[dict[str, Any]]:
    """Return latest outreach activity events with company and contact names."""
    safe_limit = max(1, int(limit))
    events: list[OutreachEvent] = list(db_session.execute(
        select(OutreachEvent)
        .order_by(OutreachEvent.event_at.desc())
        .limit(safe_limit)
    ).scalars().all())

    result: list[dict[str, Any]] = []
    for event in events:
        company = db_session.get(Company, event.company_id) if event.company_id else None
        contact = db_session.get(Contact, event.contact_id) if event.contact_id else None
        result.append({
            "timestamp": event.event_at,
            "company_name": str(company.name or "") if company else "",
            "contact_name": str(contact.full_name or "") if contact else "",
            "event_type": str(event.event_type or ""),
        })
    return result


def _probe_url(url: str) -> dict[str, str]:
    try:
        response = requests.get(url, timeout=5)
        if response.ok:
            return _ok("reachable")
        return _error(f"HTTP {response.status_code}")
    except Exception as exc:
        return _error(str(exc))


def _ok(message: str) -> dict[str, str]:
    return {"status": "ok", "message": message}


def _warning(message: str) -> dict[str, str]:
    return {"status": "warning", "message": message}


def _error(message: str) -> dict[str, str]:
    return {"status": "error", "message": message}
