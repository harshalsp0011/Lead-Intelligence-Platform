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
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from agents.outreach import followup_scheduler

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


def update_lead_status(company_id: str, new_status: str, db_session: Session) -> bool:
    """Update company status when status is valid and row exists."""
    normalized = (new_status or "").strip().lower()
    if normalized not in _VALID_STATUSES:
        return False

    updated_rows = db_session.execute(
        text(
            """
            UPDATE companies
            SET status = :new_status,
                updated_at = NOW()
            WHERE id = :company_id
            RETURNING id
            """
        ),
        {
            "company_id": company_id,
            "new_status": normalized,
        },
    ).all()

    if not updated_rows:
        db_session.rollback()
        return False

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

    db_session.execute(
        text(
            """
            UPDATE outreach_events
            SET reply_content = :reply_content,
                reply_sentiment = :reply_sentiment,
                event_type = 'replied',
                event_at = NOW()
            WHERE company_id = :company_id
              AND event_type IN ('sent', 'followup_sent', 'opened', 'clicked')
            """
        ),
        {
            "company_id": company_id,
            "reply_content": reply_content,
            "reply_sentiment": sentiment,
        },
    )

    followup_scheduler.cancel_followups(company_id=company_id, db_session=db_session)
    db_session.commit()


def mark_unsubscribed(contact_id: str, db_session: Session) -> None:
    """Mark contact unsubscribed, cancel follow-ups, and archive company if needed."""
    company_row = db_session.execute(
        text(
            """
            SELECT company_id
            FROM contacts
            WHERE id = :contact_id
            LIMIT 1
            """
        ),
        {"contact_id": contact_id},
    ).mappings().first()

    db_session.execute(
        text(
            """
            UPDATE contacts
            SET unsubscribed = true
            WHERE id = :contact_id
            """
        ),
        {"contact_id": contact_id},
    )

    company_id = str((company_row or {}).get("company_id") or "")
    if company_id:
        followup_scheduler.cancel_followups(company_id=company_id, db_session=db_session)

        remaining_active = db_session.execute(
            text(
                """
                SELECT 1
                FROM contacts
                WHERE company_id = :company_id
                  AND COALESCE(unsubscribed, false) = false
                LIMIT 1
                """
            ),
            {"company_id": company_id},
        ).first()

        if remaining_active is None:
            db_session.execute(
                text(
                    """
                    UPDATE companies
                    SET status = 'archived',
                        updated_at = NOW()
                    WHERE id = :company_id
                    """
                ),
                {"company_id": company_id},
            )

    db_session.commit()


def mark_bounced(contact_id: str, db_session: Session) -> None:
    """Mark contact as unverified and log bounced event."""
    row = db_session.execute(
        text(
            """
            SELECT company_id
            FROM contacts
            WHERE id = :contact_id
            LIMIT 1
            """
        ),
        {"contact_id": contact_id},
    ).mappings().first()

    company_id = str((row or {}).get("company_id") or "")

    db_session.execute(
        text(
            """
            UPDATE contacts
            SET verified = false
            WHERE id = :contact_id
            """
        ),
        {"contact_id": contact_id},
    )

    db_session.execute(
        text(
            """
            INSERT INTO outreach_events (
                company_id,
                contact_id,
                event_type,
                event_at,
                reply_content,
                follow_up_number,
                sales_alerted
            )
            VALUES (
                :company_id,
                :contact_id,
                'bounced',
                NOW(),
                :reply_content,
                0,
                false
            )
            """
        ),
        {
            "company_id": company_id or None,
            "contact_id": contact_id,
            "reply_content": f"Email bounced for contact {contact_id} — finding alternative contact",
        },
    )

    logger.info("Email bounced for contact %s — finding alternative contact", contact_id)
    db_session.commit()


def mark_opened(company_id: str, contact_id: str, db_session: Session) -> None:
    """Insert opened event only; do not change lead status."""
    db_session.execute(
        text(
            """
            INSERT INTO outreach_events (
                company_id,
                contact_id,
                event_type,
                event_at,
                follow_up_number,
                sales_alerted
            )
            VALUES (
                :company_id,
                :contact_id,
                'opened',
                NOW(),
                0,
                false
            )
            """
        ),
        {
            "company_id": company_id,
            "contact_id": contact_id,
        },
    )

    db_session.commit()


def mark_sales_alerted(outreach_event_id: str, db_session: Session) -> None:
    """Mark one outreach event as sales-alerted with current timestamp."""
    db_session.execute(
        text(
            """
            UPDATE outreach_events
            SET sales_alerted = true,
                alerted_at = NOW()
            WHERE id = :outreach_event_id
            """
        ),
        {"outreach_event_id": outreach_event_id},
    )
    db_session.commit()
