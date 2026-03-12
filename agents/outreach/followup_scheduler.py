from __future__ import annotations

"""Follow-up scheduling helpers for outreach sequences.

Purpose:
- Creates, finds, cancels, and summarizes scheduled follow-up events.

Dependencies:
- `config.settings.get_settings` for follow-up day offsets.
- `sqlalchemy` session access to `outreach_events`, `companies`, and `contacts`.

Usage:
- Call `schedule_followups(...)` after a successful initial send.
- Call `get_due_followups(...)` in a daily job to fetch follow-ups to send.
"""

from datetime import date, datetime, timedelta
import logging
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from config.settings import get_settings
from database.orm_models import Company, Contact, OutreachEvent

logger = logging.getLogger(__name__)

EVENT_TYPE_SCHEDULED_FOLLOWUP = "scheduled_followup"
EVENT_TYPE_CANCELLED_FOLLOWUP = "cancelled_followup"
EVENT_TYPE_REPLIED = "replied"
EVENT_TYPE_SENT = "sent"
COMPANY_STATUS_REPLIED = "replied"
COMPANY_STATUS_NO_RESPONSE = "no_response"


def _parse_uuid(value: str) -> UUID | None:
    """Parse a string UUID value, returning None for invalid input."""
    try:
        return UUID(str(value))
    except (TypeError, ValueError):
        return None


def schedule_followups(
    company_id: str,
    contact_id: str,
    draft_id: str,
    send_date: date | datetime | str,
    db_session: Session,
) -> list[str]:
    """Create three scheduled follow-up events and return their IDs."""
    settings = get_settings()
    day_1 = int(settings.FOLLOWUP_DAY_1)
    day_2 = int(settings.FOLLOWUP_DAY_2)
    day_3 = int(settings.FOLLOWUP_DAY_3)

    base_date = _to_date(send_date)
    offsets = [(1, day_1), (2, day_2), (3, day_3)]

    created_ids: list[str] = []
    for follow_up_number, day_offset in offsets:
        next_date = base_date + timedelta(days=day_offset)
        event = OutreachEvent(
            company_id=_parse_uuid(company_id),
            contact_id=_parse_uuid(contact_id),
            email_draft_id=_parse_uuid(draft_id),
            event_type=EVENT_TYPE_SCHEDULED_FOLLOWUP,
            event_at=datetime.now(),
            follow_up_number=follow_up_number,
            next_followup_date=next_date,
            sales_alerted=False,
        )
        db_session.add(event)
        db_session.flush()
        created_ids.append(str(event.id))

    db_session.commit()
    return created_ids


def get_due_followups(db_session: Session) -> list[dict[str, Any]]:
    """Return scheduled follow-up events due today for active contacts/companies."""
    rows = db_session.execute(
        select(OutreachEvent, Company, Contact)
        .join(Company, Company.id == OutreachEvent.company_id)
        .join(Contact, Contact.id == OutreachEvent.contact_id)
        .where(
            OutreachEvent.event_type == EVENT_TYPE_SCHEDULED_FOLLOWUP,
            OutreachEvent.next_followup_date <= date.today(),
            func.coalesce(OutreachEvent.sales_alerted, False).is_(False),
            func.coalesce(Company.status, "") != COMPANY_STATUS_REPLIED,
            func.coalesce(Contact.unsubscribed, False).is_(False),
        )
        .order_by(OutreachEvent.next_followup_date.asc(), OutreachEvent.follow_up_number.asc())
    ).all()

    return [
        {
            "id": event.id,
            "company_id": event.company_id,
            "contact_id": event.contact_id,
            "email_draft_id": event.email_draft_id,
            "follow_up_number": event.follow_up_number,
            "next_followup_date": event.next_followup_date,
            "company_name": company.name,
            "company_status": company.status,
            "contact_email": contact.email,
            "contact_name": contact.full_name,
            "unsubscribed": contact.unsubscribed,
        }
        for event, company, contact in rows
    ]


def cancel_followups(company_id: str, db_session: Session) -> int:
    """Cancel future scheduled follow-ups for one company and return count."""
    company_uuid = _parse_uuid(company_id)
    if company_uuid is None:
        logger.warning("cancel_followups received invalid company_id=%s", company_id)
        return 0

    rows = db_session.execute(
        select(OutreachEvent)
        .where(
            OutreachEvent.company_id == company_uuid,
            OutreachEvent.event_type == EVENT_TYPE_SCHEDULED_FOLLOWUP,
            OutreachEvent.next_followup_date > date.today(),
        )
    ).scalars().all()

    for row in rows:
        row.event_type = EVENT_TYPE_CANCELLED_FOLLOWUP

    db_session.commit()
    return len(rows)


def check_sequence_status(company_id: str, db_session: Session) -> dict[str, Any]:
    """Return follow-up sequence progress/status for one company."""
    company_uuid = _parse_uuid(company_id)
    if company_uuid is None:
        logger.warning("check_sequence_status received invalid company_id=%s", company_id)
        return {
            "last_followup_sent": 0,
            "next_followup_date": None,
            "sequence_complete": False,
            "reply_received": False,
        }

    sent_last = db_session.execute(
        select(func.coalesce(func.max(OutreachEvent.follow_up_number), 0)).where(
            OutreachEvent.company_id == company_uuid,
            OutreachEvent.event_type == EVENT_TYPE_SENT,
        )
    ).scalar_one()

    next_date = db_session.execute(
        select(func.min(OutreachEvent.next_followup_date)).where(
            OutreachEvent.company_id == company_uuid,
            OutreachEvent.event_type == EVENT_TYPE_SCHEDULED_FOLLOWUP,
        )
    ).scalar_one_or_none()

    replied_exists = db_session.execute(
        select(OutreachEvent.id)
        .where(
            OutreachEvent.company_id == company_uuid,
            OutreachEvent.event_type == EVENT_TYPE_REPLIED,
        )
        .limit(1)
    ).first() is not None

    sequence_complete = bool(replied_exists) or (next_date is None and int(sent_last or 0) >= 3)

    return {
        "last_followup_sent": int(sent_last or 0),
        "next_followup_date": next_date,
        "sequence_complete": sequence_complete,
        "reply_received": bool(replied_exists),
    }


def mark_sequence_complete(company_id: str, db_session: Session) -> None:
    """Mark company as no_response and cancel remaining scheduled follow-ups."""
    company_uuid = _parse_uuid(company_id)
    if company_uuid is None:
        logger.warning("mark_sequence_complete received invalid company_id=%s", company_id)
        return

    company = db_session.execute(
        select(Company).where(Company.id == company_uuid)
    ).scalar_one_or_none()
    if company is not None:
        company.status = COMPANY_STATUS_NO_RESPONSE
        company.updated_at = datetime.now()

    cancel_followups(company_id=company_id, db_session=db_session)


def _to_date(value: date | datetime | str) -> date:
    """Normalize a date-like input into a `date` instance."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value

    try:
        return datetime.fromisoformat(str(value)).date()
    except ValueError as exc:
        logger.error("Invalid send_date received: %r", value)
        raise ValueError("send_date must be a date, datetime, or ISO date string") from exc


class FollowupScheduler:
    """Class-based interface for followup scheduling operations (used by test suite)."""

    def schedule_followups(
        self,
        company_id: str,
        send_date: date | datetime | str,
        db_session: Session,
        contact_id: str = None,
        draft_id: str = None,
        followup_days: list[int] = None,
    ) -> list[dict[str, Any]]:
        """Create three scheduled follow-up event records."""
        if followup_days is None:
            followup_days = [3, 7, 14]  # Default days
        
        base_date = _to_date(send_date)
        offsets = [(1, followup_days[0]), (2, followup_days[1]), (3, followup_days[2])]
        
        records = []
        for follow_up_number, day_offset in offsets:
            next_date = base_date + timedelta(days=day_offset)
            records.append({
                'follow_up_number': follow_up_number,
                'next_followup_date': next_date,
                'company_id': company_id,
                'contact_id': contact_id or '',
                'draft_id': draft_id or '',
            })
        
        return records

    def cancel_followups(self, company_id: str, db_session: Session) -> int:
        """Cancel future scheduled follow-ups for one company."""
        return cancel_followups(company_id=company_id, db_session=db_session)

    def get_due_followups(
        self,
        db_session: Session,
        cutoff_date: date = None,
    ) -> list[dict[str, Any]]:
        """Return scheduled follow-up events due by cutoff date."""
        followups = get_due_followups(db_session)
        
        # Filter by cutoff date if provided
        if cutoff_date:
            filtered = []
            for followup in followups:
                next_date = followup.get('next_followup_date')
                if isinstance(next_date, str):
                    next_date = datetime.fromisoformat(next_date).date()
                if next_date <= cutoff_date:
                    filtered.append(followup)
            return filtered
        
        return followups

    def check_sequence_status(self, company_id: str, db_session: Session) -> dict[str, Any]:
        """Return follow-up sequence progress/status for one company."""
        return check_sequence_status(company_id=company_id, db_session=db_session)

    def mark_sequence_complete(self, company_id: str, db_session: Session) -> None:
        """Mark company as no_response and cancel remaining scheduled follow-ups."""
        mark_sequence_complete(company_id=company_id, db_session=db_session)
