from __future__ import annotations

"""Lead/contact status update helpers for tracker events.

Purpose:
- Applies database status changes after reply, unsubscribe, bounce, and open events.

Dependencies:
- `sqlalchemy` session access to `companies`, `contacts`, and `outreach_events`.
- `agents.outreach.followup_scheduler` to cancel scheduled follow-up rows.

Usage:
- Call these helpers from `tracker_agent.process_event(...)` when normalized
  webhook events are received.
"""

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from agents.outreach import followup_scheduler
from database.orm_models import Company, Contact, OutreachEvent

logger = logging.getLogger(__name__)

_VALID_STATUSES = {
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
}


def _parse_uuid(value: str, label: str = "id") -> uuid.UUID:
    """Parse a UUID string; raises ValueError with a clear message on failure."""
    try:
        return uuid.UUID(str(value))
    except (ValueError, AttributeError) as exc:
        raise ValueError(f"Invalid {label}: {value!r}") from exc


def update_lead_status(company_id: str, new_status: str, db_session: Session) -> bool:
    """Update company status when status is valid and row exists."""
    normalized = (new_status or "").strip().lower()
    if normalized not in _VALID_STATUSES:
        return False

    company = db_session.get(Company, _parse_uuid(company_id, "company_id"))
    if company is None:
        return False
    company.status = normalized
    company.updated_at = datetime.now(timezone.utc)
    db_session.commit()
    return True


def mark_replied(
    company_id: str,
    reply_content: str,
    sentiment: str,
    db_session: Session,
) -> None:
    """Mark lead as replied, record reply text/sentiment, and stop follow-ups."""
    update_lead_status(company_id=company_id, new_status="replied", db_session=db_session)

    cid = _parse_uuid(company_id, "company_id")
    _reply_event_types = ("sent", "followup_sent", "opened", "clicked")
    events: list[OutreachEvent] = list(db_session.execute(
        select(OutreachEvent).where(
            OutreachEvent.company_id == cid,
            OutreachEvent.event_type.in_(list(_reply_event_types)),
        )
    ).scalars().all())
    now = datetime.now(timezone.utc)
    for event in events:
        event.reply_content = reply_content
        event.reply_sentiment = sentiment
        event.event_type = "replied"
        event.event_at = now

    followup_scheduler.cancel_followups(company_id=company_id, db_session=db_session)
    db_session.commit()


def mark_unsubscribed(contact_id: str, db_session: Session) -> None:
    """Mark contact unsubscribed, cancel follow-ups, and archive company if needed."""
    cid = _parse_uuid(contact_id, "contact_id")
    contact = db_session.get(Contact, cid)
    if contact is None:
        return

    company_id_obj: uuid.UUID | None = contact.company_id
    contact.unsubscribed = True

    if company_id_obj is not None:
        followup_scheduler.cancel_followups(
            company_id=str(company_id_obj), db_session=db_session
        )

        remaining_active: Contact | None = db_session.execute(
            select(Contact)
            .where(
                Contact.company_id == company_id_obj,
                Contact.unsubscribed == False,  # noqa: E712
            )
            .limit(1)
        ).scalar()

        if remaining_active is None:
            company = db_session.get(Company, company_id_obj)
            if company is not None:
                company.status = "archived"
                company.updated_at = datetime.now(timezone.utc)

    db_session.commit()


def mark_bounced(contact_id: str, db_session: Session) -> None:
    """Mark contact as unverified and log bounced event."""
    cid = _parse_uuid(contact_id, "contact_id")
    contact = db_session.get(Contact, cid)
    if contact is None:
        return

    company_id_obj: uuid.UUID | None = contact.company_id
    contact.verified = False

    bounce_event = OutreachEvent(
        id=uuid.uuid4(),
        company_id=company_id_obj,
        contact_id=cid,
        event_type="bounced",
        event_at=datetime.now(timezone.utc),
        reply_content=f"Email bounced for contact {contact_id} — finding alternative contact",
        follow_up_number=0,
        sales_alerted=False,
    )
    db_session.add(bounce_event)

    logger.info("Email bounced for contact %s — finding alternative contact", contact_id)
    db_session.commit()


class StatusUpdater:
    """Class interface for lead/contact status update functions.

    Wraps module-level status functions for class-based access in tests and
    structured service flows. The ``update_lead_status`` method raises
    ``ValueError`` for invalid statuses (whereas the underlying function returns
    ``False``) so callers get an immediate, explicit signal of bad input.
    """

    def update_lead_status(
        self,
        company_id: str,
        new_status: str,
        db_session: Session,
    ) -> bool:
        """Update company status; raises ValueError for unrecognized status values."""
        normalized = (new_status or "").strip().lower()
        if normalized not in _VALID_STATUSES:
            raise ValueError(
                f"Invalid lead status: '{new_status}'. "
                f"Must be one of: {sorted(_VALID_STATUSES)}"
            )
        return update_lead_status(company_id, new_status, db_session)

    def mark_replied(
        self,
        company_id: str,
        reply_content: str,
        sentiment: str,
        db_session: Session,
    ) -> None:
        """Mark lead as replied and cancel pending follow-ups."""
        mark_replied(company_id, reply_content, sentiment, db_session)

    def mark_unsubscribed(self, contact_id: str, db_session: Session) -> None:
        """Flag contact as unsubscribed and archive company if no active contacts remain."""
        mark_unsubscribed(contact_id, db_session)

    def mark_bounced(self, contact_id: str, db_session: Session) -> None:
        """Invalidate bounced contact and log the bounce event."""
        mark_bounced(contact_id, db_session)


def mark_opened(company_id: str, contact_id: str, db_session: Session) -> None:
    """Insert opened event only; do not change lead status."""
    open_event = OutreachEvent(
        id=uuid.uuid4(),
        company_id=_parse_uuid(company_id, "company_id"),
        contact_id=_parse_uuid(contact_id, "contact_id"),
        event_type="opened",
        event_at=datetime.now(timezone.utc),
        follow_up_number=0,
        sales_alerted=False,
    )
    db_session.add(open_event)
    db_session.commit()


def mark_sales_alerted(outreach_event_id: str, db_session: Session) -> None:
    """Mark one outreach event as sales-alerted with current timestamp."""
    event = db_session.get(
        OutreachEvent, _parse_uuid(outreach_event_id, "outreach_event_id")
    )
    if event is not None:
        event.sales_alerted = True
        event.alerted_at = datetime.now(timezone.utc)
        db_session.commit()
