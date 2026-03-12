from __future__ import annotations

"""Outreach agent queue handlers.

Purpose:
- Processes approved first-email queue and scheduled follow-up queue operations.

Dependencies:
- `agents.outreach.email_sender` for provider send + daily-limit checks.
- `agents.outreach.followup_scheduler` for due follow-up records and sequence status updates.
- `agents.outreach.sequence_manager` for follow-up subject/body generation.
- `sqlalchemy` session for `email_drafts`, `contacts`, `outreach_events`, and `companies`.

Usage:
- Call `process_followup_queue(db_session)` from a scheduler job.
- Call `get_approved_queue(db_session)` before first-send queue processing.
"""

from datetime import date, datetime, timezone
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from agents.outreach import email_sender, followup_scheduler, sequence_manager
from config.settings import get_settings
from database.orm_models import EmailDraft, OutreachEvent


def _try_parse_uuid(value: str) -> uuid.UUID | None:
    """Parse a UUID value and return None for blank or invalid input."""
    if not value:
        return None
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError):
        return None


def process_followup_queue(db_session: Session) -> int:
    """Process due follow-ups and return number sent successfully."""
    due_followups = followup_scheduler.get_due_followups(db_session)
    sent_count = 0

    for followup in due_followups:
        contact_id = str(followup.get("contact_id") or "")
        company_id = str(followup.get("company_id") or "")
        original_draft_id = str(followup.get("email_draft_id") or "")
        follow_up_number = int(followup.get("follow_up_number") or 0)

        # Skip unsubscribed contacts.
        if bool(followup.get("unsubscribed")):
            continue

        # Build follow-up subject/body from templates + LLM polish.
        followup_email = sequence_manager.build_followup_email(
            original_draft_id=original_draft_id,
            follow_up_number=follow_up_number,
            db_session=db_session,
        )

        followup_draft_id = _create_followup_draft(
            original_draft_id=original_draft_id,
            company_id=company_id,
            contact_id=contact_id,
            subject=str(followup_email.get("subject") or ""),
            body=str(followup_email.get("body") or ""),
            follow_up_number=follow_up_number,
            db_session=db_session,
        )

        send_result = email_sender.send_email(followup_draft_id, db_session)
        if not bool(send_result.get("success")):
            continue

        sent_count += 1

        # Mark scheduled record as sent.
        event_id = _try_parse_uuid(str(followup.get("id") or ""))
        if event_id is not None:
            scheduled_event = db_session.get(OutreachEvent, event_id)
            if scheduled_event is not None:
                scheduled_event.event_type = "followup_sent"
                scheduled_event.event_at = datetime.now(timezone.utc)
                scheduled_event.reply_content = f"message_id:{send_result.get('message_id', '')}"

        if follow_up_number < 3:
            # Ensure future follow-ups exist in case they were not pre-scheduled.
            parsed_company_id = _try_parse_uuid(company_id)
            parsed_contact_id = _try_parse_uuid(contact_id)
            existing_future = None
            if parsed_company_id is not None and parsed_contact_id is not None:
                existing_future = db_session.execute(
                    select(OutreachEvent.id)
                    .where(
                        OutreachEvent.company_id == parsed_company_id,
                        OutreachEvent.contact_id == parsed_contact_id,
                        OutreachEvent.event_type == "scheduled_followup",
                        OutreachEvent.follow_up_number > follow_up_number,
                    )
                    .limit(1)
                ).scalar()

            if existing_future is None:
                followup_scheduler.schedule_followups(
                    company_id=company_id,
                    contact_id=contact_id,
                    draft_id=followup_draft_id,
                    send_date=date.today(),
                    db_session=db_session,
                )
        else:
            followup_scheduler.mark_sequence_complete(company_id=company_id, db_session=db_session)

        db_session.commit()

    return sent_count


def get_approved_queue(db_session: Session) -> list[dict[str, Any]]:
    """Return approved draft rows that do not yet have a sent event."""
    drafts = db_session.execute(
        select(EmailDraft)
        .where(EmailDraft.approved_human.is_(True))
        .order_by(EmailDraft.created_at.asc())
    ).scalars().all()

    queue: list[dict[str, Any]] = []
    for draft in drafts:
        sent_event_exists = db_session.execute(
            select(OutreachEvent.id)
            .where(
                OutreachEvent.email_draft_id == draft.id,
                OutreachEvent.event_type.in_(["sent", "followup_sent"]),
            )
            .limit(1)
        ).scalar()
        if sent_event_exists is not None:
            continue

        queue.append(
            {
                "id": str(draft.id),
                "company_id": str(draft.company_id) if draft.company_id else None,
                "contact_id": str(draft.contact_id) if draft.contact_id else None,
                "subject_line": draft.subject_line,
                "body": draft.body,
                "savings_estimate": draft.savings_estimate,
                "template_used": draft.template_used,
                "created_at": draft.created_at,
            }
        )

    return queue


def check_daily_limit(db_session: Session) -> dict[str, Any]:
    """Return daily send cap status with remaining count included."""
    base = email_sender.check_daily_limit(db_session)
    limit = int(getattr(get_settings(), "EMAIL_DAILY_LIMIT", 50) or 50)
    sent_today = int(base.get("sent_today") or 0)

    return {
        "within_limit": bool(base.get("within_limit")),
        "sent_today": sent_today,
        "remaining": max(0, limit - sent_today),
    }


def log_outreach_run(sent_count: int, skipped_count: int, followup_count: int) -> None:
    """Print a summary line block for one outreach run."""
    print(
        "Outreach run complete:\n"
        f"First emails sent: {int(sent_count)}\n"
        f"Followups sent: {int(followup_count)}\n"
        f"Skipped (limit/unsubscribed): {int(skipped_count)}"
    )


def _create_followup_draft(
    original_draft_id: str,
    company_id: str,
    contact_id: str,
    subject: str,
    body: str,
    follow_up_number: int,
    db_session: Session,
) -> str:
    parsed_original_draft_id = _try_parse_uuid(original_draft_id)
    source_draft = (
        db_session.get(EmailDraft, parsed_original_draft_id)
        if parsed_original_draft_id is not None
        else None
    )
    savings_estimate = str((source_draft.savings_estimate if source_draft else "") or "")

    followup_draft = EmailDraft(
        id=uuid.uuid4(),
        company_id=_try_parse_uuid(company_id),
        contact_id=_try_parse_uuid(contact_id),
        subject_line=subject,
        body=body,
        savings_estimate=savings_estimate,
        template_used=f"followup_day{follow_up_number}",
        approved_human=True,
        edited_human=False,
    )
    db_session.add(followup_draft)
    db_session.flush()

    return str(followup_draft.id)
