from __future__ import annotations

"""Tracker agent lifecycle checks and event entrypoints.

Purpose:
- Hosts tracker orchestration hooks and daily stuck-lead health checks.

Dependencies:
- `sqlalchemy` session queries against `companies`, `email_drafts`, and `outreach_events`.
- `agents.outreach.followup_scheduler` to complete/cancel stale follow-up sequences.
- `agents.tracker.status_updater.update_lead_status` for canonical status updates.
- `config.settings.get_settings` and `requests` for Slack reminder notifications.

Usage:
- Call `run_daily_checks(db_session)` from a scheduled daily monitoring job.
- Keep `process_event(event)` as webhook dispatch entrypoint for tracker processing.
"""

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import requests
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from agents.outreach import followup_scheduler
from agents.tracker.status_updater import update_lead_status
from config.settings import get_settings
from database.orm_models import Company, EmailDraft, OutreachEvent


def _parse_uuid(value: str, label: str = "id") -> uuid.UUID:
    """Parse a UUID string; raises ValueError with a clear message on failure."""
    try:
        return uuid.UUID(str(value))
    except (ValueError, AttributeError) as exc:
        raise ValueError(f"Invalid {label}: {value!r}") from exc

logger = logging.getLogger(__name__)

_TERMINAL_STATUSES = {"won", "lost", "no_response", "archived", "unsubscribed"}


def process_event(event: dict[str, Any]) -> None:
    """Placeholder webhook event entrypoint for tracker routing."""
    logger.info("Tracker event received: %s", event)


def check_stuck_leads(db_session: Session) -> list[str]:
    """Return company IDs stale for 5+ days in non-terminal statuses."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=5)
    company_ids: list[str] = [
        str(cid) for cid in db_session.execute(
            select(Company.id)
            .where(
                Company.updated_at < cutoff,
                Company.status.not_in(list(_TERMINAL_STATUSES)),
            )
            .order_by(Company.updated_at.asc())
        ).scalars().all()
    ]

    for company_id in company_ids:
        logger.warning("Stuck lead detected: %s", company_id)

    return company_ids


def resolve_stuck_lead(company_id: str, db_session: Session) -> str:
    """Resolve one stuck lead based on current state and related activity."""
    cid = _parse_uuid(company_id, "company_id")
    company = db_session.get(Company, cid)

    if not company:
        return "not_found"

    status = str(company.status or "").strip().lower()

    if status == "contacted":
        last_sent_at = db_session.execute(
            select(func.max(OutreachEvent.event_at)).where(
                OutreachEvent.company_id == cid,
                OutreachEvent.event_type.in_(["sent", "followup_sent"]),
            )
        ).scalar()

        replied_exists = db_session.execute(
            select(OutreachEvent.id)
            .where(
                OutreachEvent.company_id == cid,
                OutreachEvent.event_type == "replied",
            )
            .limit(1)
        ).scalar() is not None

        if last_sent_at is not None and not replied_exists:
            stale_cutoff = datetime.now(timezone.utc) - timedelta(days=14)
            if last_sent_at < stale_cutoff:
                followup_scheduler.mark_sequence_complete(company_id=company_id, db_session=db_session)
                update_lead_status(company_id=company_id, new_status="no_response", db_session=db_session)
                return "marked_no_response"

    if status == "scored":
        has_draft = db_session.execute(
            select(EmailDraft.id)
            .where(EmailDraft.company_id == cid)
            .limit(1)
        ).scalar() is not None

        if not has_draft:
            logger.warning("Lead scored but no email drafted yet: %s", company_id)
            return "needs_writer_attention"

    if status == "draft_created":
        approved_exists = db_session.execute(
            select(EmailDraft.id)
            .where(
                EmailDraft.company_id == cid,
                EmailDraft.approved_human == True,  # noqa: E712
            )
            .limit(1)
        ).scalar() is not None

        if not approved_exists:
            logger.warning("Draft waiting human approval > 5 days: %s", company_id)
            _send_approval_reminder(
                company_id=company_id,
                company_name=str(company.name or "Unknown Company"),
            )
            return "reminded_approval_needed"

    return "no_action"


def run_daily_checks(db_session: Session) -> dict[str, int]:
    """Run stale-lead checks and return summary counts."""
    stuck = check_stuck_leads(db_session)

    resolved_count = 0
    needs_attention_count = 0

    for company_id in stuck:
        action = resolve_stuck_lead(company_id=company_id, db_session=db_session)

        if action in {"marked_no_response", "reminded_approval_needed"}:
            resolved_count += 1
        elif action in {"needs_writer_attention"}:
            needs_attention_count += 1

    return {
        "stuck_found": len(stuck),
        "resolved": resolved_count,
        "needs_attention": needs_attention_count,
    }


def _send_approval_reminder(company_id: str, company_name: str) -> None:
    settings = get_settings()
    webhook = str(settings.SLACK_WEBHOOK_URL or "").strip()
    if not webhook:
        return

    message = (
        "Draft waiting human approval > 5 days\n"
        f"Company: {company_name}\n"
        f"Lead ID: {company_id}\n"
        f"Review: http://localhost:3000/leads/{company_id}"
    )

    try:
        requests.post(webhook, json={"text": message}, timeout=10)
    except Exception:
        logger.exception("Failed to send Slack approval reminder for %s", company_id)
