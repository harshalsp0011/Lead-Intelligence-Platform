from __future__ import annotations

"""Daily Airflow DAG for tracking followups, email limits, and stale lead resolution.

Purpose:
- Runs daily to send scheduled followups, check daily email limits, resolve stale
  leads, mark completed sequences, and send daily pipeline summary alerts.

Dependencies:
- `airflow` for DAG and PythonOperator definitions.
- `database.connection.SessionLocal` for PostgreSQL sessions.
- `agents.outreach.followup_scheduler` for due followup and sequence tracking.
- `agents.outreach.sequence_manager` for followup email construction.
- `agents.outreach.email_sender` for email delivery and limit checks.
- `agents.tracker.tracker_agent` for stuck lead detection.
- `agents.tracker.status_updater` for lead status updates.
- `config.settings.get_settings` for Slack webhook configuration.

Usage:
- Place this file in Airflow's DAGs folder and ensure the project root is
  importable.
"""

import logging
import sys
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

from airflow import DAG
from airflow.operators.python import PythonOperator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

from agents.outreach import email_sender, followup_scheduler, sequence_manager
from agents.tracker import status_updater, tracker_agent
from config.settings import get_settings
from database.connection import SessionLocal
from database.orm_models import Company, OutreachEvent

logger = logging.getLogger(__name__)

DUE_FOLLOWUPS_XCOM_KEY = "due_followups"
SENT_FOLLOWUPS_COUNT_XCOM_KEY = "sent_followups_count"
DAILY_LIMIT_REMAINING_XCOM_KEY = "daily_limit_remaining"
STALE_RESOLVED_COUNT_XCOM_KEY = "stale_resolved_count"
SEQUENCES_COMPLETED_COUNT_XCOM_KEY = "sequences_completed_count"


@contextmanager
def db_session_scope() -> Iterator[Session]:
    """Yield a DB session and always close it after task execution."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()



def _format_currency(value: float) -> str:
    """Format a number as a currency string."""
    if value < 0:
        return f"-${abs(value):,.0f}"
    return f"${value:,.0f}"


def check_followup_queue(**context: Any) -> list[dict[str, Any]]:
    """Fetch and push due followups scheduled for today."""
    with db_session_scope() as db_session:
        due_followups = followup_scheduler.get_due_followups(db_session)

    task_instance = context["ti"]
    task_instance.xcom_push(key=DUE_FOLLOWUPS_XCOM_KEY, value=due_followups)

    logger.info("Found %d followups due today", len(due_followups))
    return due_followups


def send_due_followups(**context: Any) -> int:
    """Send all due followups and update outreach event records."""
    task_instance = context["ti"]
    due_followups = (
        task_instance.xcom_pull(
            task_ids="task_check_followup_queue",
            key=DUE_FOLLOWUPS_XCOM_KEY,
        )
        or []
    )

    if not due_followups:
        task_instance.xcom_push(key=SENT_FOLLOWUPS_COUNT_XCOM_KEY, value=0)
        return 0

    sent_count = 0
    settings = get_settings()
    from_email = str(getattr(settings, "SENDGRID_FROM_EMAIL", "") or "").strip()

    with db_session_scope() as db_session:
        for followup_record in due_followups:
            try:
                # Skip unsubscribed contacts
                if followup_record.get("unsubscribed"):
                    logger.info(
                        "Skipping unsubscribed contact for company %s",
                        followup_record.get("company_id"),
                    )
                    continue

                draft_id = str(followup_record.get("email_draft_id") or "")
                follow_up_number = int(followup_record.get("follow_up_number") or 0)
                company_id = str(followup_record.get("company_id") or "")
                contact_email = str(followup_record.get("contact_email") or "")
                contact_name = str(followup_record.get("contact_name") or "")
                event_id = str(followup_record.get("id") or "")

                # Build followup email
                followup_email = sequence_manager.build_followup_email(
                    draft_id,
                    follow_up_number,
                    db_session,
                )

                # Send via SendGrid
                send_result = email_sender.send_via_sendgrid(
                    to_email=contact_email,
                    to_name=contact_name,
                    subject=followup_email.get("subject", ""),
                    body=followup_email.get("body", ""),
                    from_email=from_email,
                )

                if not send_result.get("success"):
                    logger.warning(
                        "Failed to send followup #%d for company %s: %s",
                        follow_up_number,
                        company_id,
                        send_result.get("message_id"),
                    )
                    continue

                # Update outreach event
                from database.orm_models import OutreachEvent as _OE  # noqa: PLC0415
                import uuid as _uuid  # noqa: PLC0415
                event_obj = db_session.get(_OE, _uuid.UUID(event_id)) if event_id else None
                if event_obj is not None:
                    event_obj.event_type = "followup_sent"
                    from datetime import datetime as _dt, timezone as _tz  # noqa: PLC0415
                    event_obj.event_at = _dt.now(_tz.utc)
                db_session.commit()

                # Schedule next followup if not on final round
                if follow_up_number < 3:
                    days_until_next = int(getattr(settings, f"FOLLOWUP_DAY_{follow_up_number + 1}", 0) or 0)
                    if days_until_next > 0:
                        next_date = datetime.now(timezone.utc) + timedelta(days=days_until_next)
                        import uuid as _uuid2  # noqa: PLC0415
                        from database.orm_models import OutreachEvent as _OE2  # noqa: PLC0415
                        from datetime import datetime as _dt2, timezone as _tz2  # noqa: PLC0415
                        _cid = _uuid2.UUID(company_id) if company_id else None
                        _ctid_raw = followup_record.get("contact_id")
                        _ctid = _uuid2.UUID(str(_ctid_raw)) if _ctid_raw else None
                        _did = _uuid2.UUID(draft_id) if draft_id else None
                        next_event = _OE2(
                            id=_uuid2.uuid4(),
                            company_id=_cid,
                            contact_id=_ctid,
                            email_draft_id=_did,
                            event_type="scheduled_followup",
                            follow_up_number=follow_up_number + 1,
                            next_followup_date=next_date.date(),
                            event_at=_dt2.now(_tz2.utc),
                        )
                        db_session.add(next_event)
                        db_session.commit()
                elif follow_up_number == 3:
                    followup_scheduler.mark_sequence_complete(company_id, db_session)

                sent_count += 1
                logger.info(
                    "Sent followup #%d to %s for company %s",
                    follow_up_number,
                    contact_email,
                    company_id,
                )

            except Exception:
                logger.exception(
                    "Error processing followup for company %s",
                    followup_record.get("company_id"),
                )
                db_session.rollback()

    task_instance.xcom_push(key=SENT_FOLLOWUPS_COUNT_XCOM_KEY, value=sent_count)
    return sent_count


def check_daily_limit(**context: Any) -> dict[str, Any] | None:
    """Check if daily email limit has been reached and alert if so."""
    with db_session_scope() as db_session:
        limit_check = email_sender.check_daily_limit(db_session)

    if not limit_check.get("within_limit"):
        sent_today = int(limit_check.get("sent_today", 0) or 0)
        logger.warning("Notification skipped — email notifier not yet implemented")

    task_instance = context["ti"]
    remaining = int(
        getattr(get_settings(), "EMAIL_DAILY_LIMIT", 50) or 50
    ) - int(limit_check.get("sent_today", 0) or 0)
    task_instance.xcom_push(key=DAILY_LIMIT_REMAINING_XCOM_KEY, value=remaining)

    return limit_check


def scan_stale_leads(**context: Any) -> int:
    """Detect and resolve stuck leads."""
    with db_session_scope() as db_session:
        stuck_company_ids = tracker_agent.check_stuck_leads(db_session)

        resolved_count = 0
        for company_id in stuck_company_ids:
            try:
                tracker_agent.resolve_stuck_lead(company_id, db_session)
                resolved_count += 1
                logger.info("Resolved stuck lead: %s", company_id)
            except Exception:
                logger.exception("Failed to resolve stuck lead: %s", company_id)

    task_instance = context["ti"]
    task_instance.xcom_push(key=STALE_RESOLVED_COUNT_XCOM_KEY, value=resolved_count)
    return resolved_count


def update_sequence_completions(**context: Any) -> int:
    """Mark sequences as complete when final followup was sent with no reply."""
    today = datetime.now(timezone.utc)
    yesterday = today - timedelta(days=1)

    completed_count = 0

    with db_session_scope() as db_session:
        # Find final followups sent yesterday or earlier with no reply
        replied_subq = (
            select(OutreachEvent.id)
            .where(
                OutreachEvent.company_id == OutreachEvent.company_id,
                OutreachEvent.event_type == "replied",
            )
        )
        rows = db_session.execute(
            select(OutreachEvent.company_id)
            .where(
                OutreachEvent.follow_up_number == 3,
                OutreachEvent.event_type == "followup_sent",
                OutreachEvent.event_at < yesterday,
                ~select(OutreachEvent.id)
                .where(
                    OutreachEvent.company_id == OutreachEvent.company_id,
                    OutreachEvent.event_type == "replied",
                )
                .correlate_except(OutreachEvent)
                .exists(),
            )
            .distinct()
        ).scalars().all()

        for company_id in rows:
            try:
                followup_scheduler.mark_sequence_complete(str(company_id), db_session)
                status_updater.update_lead_status(str(company_id), "no_response", db_session)
                completed_count += 1
                logger.info("Marked sequence complete for company %s", company_id)
            except Exception:
                logger.exception("Failed to mark sequence complete for company %s", company_id)

    task_instance = context["ti"]
    task_instance.xcom_push(key=SEQUENCES_COMPLETED_COUNT_XCOM_KEY, value=completed_count)
    return completed_count


def send_daily_summary(**context: Any) -> None:
    """Send daily pipeline summary to Slack."""
    task_instance = context["ti"]

    # Pull counts from all previous tasks
    followup_count = int(
        task_instance.xcom_pull(
            task_ids="task_send_followups",
            key=SENT_FOLLOWUPS_COUNT_XCOM_KEY,
        )
        or 0
    )
    stale_count = int(
        task_instance.xcom_pull(
            task_ids="task_scan_stale_leads",
            key=STALE_RESOLVED_COUNT_XCOM_KEY,
        )
        or 0
    )
    completed_count = int(
        task_instance.xcom_pull(
            task_ids="task_update_sequence_completions",
            key=SEQUENCES_COMPLETED_COUNT_XCOM_KEY,
        )
        or 0
    )

    with db_session_scope() as db_session:
        # Count new replies received today
        today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        reply_count = int(db_session.execute(
            select(func.count(func.distinct(OutreachEvent.company_id))).where(
                OutreachEvent.event_type == "replied",
                OutreachEvent.event_at >= today_start,
            )
        ).scalar_one() or 0)

        # Count hot leads (replied but not yet alerted)
        hot_count = int(db_session.execute(
            select(func.count(func.distinct(OutreachEvent.company_id))).where(
                OutreachEvent.event_type == "replied",
                (OutreachEvent.sales_alerted == False) | (OutreachEvent.sales_alerted.is_(None)),  # noqa: E712
            )
        ).scalar_one() or 0)

        # Count active leads in pipeline
        active_count = int(db_session.execute(
            select(func.count(func.distinct(Company.id))).where(
                Company.status.not_in(["lost", "archived", "no_response", "won"]),
                )
            ).scalar_one() or 0)

    today_str = datetime.now().strftime("%A, %B %d, %Y")

    message = (
        f"Daily Pipeline Summary — {today_str}\n"
        f"Followups sent: {followup_count}\n"
        f"New replies received: {reply_count}\n"
        f"Hot leads needing action: {hot_count}\n"
        f"Stale leads resolved: {stale_count}\n"
        f"Sequences completed: {completed_count}\n"
        f"Total active pipeline: {active_count}\n"
        "Dashboard: http://localhost:3000"
    )
    logger.warning("Notification skipped — email notifier not yet implemented")


default_args = {
    "owner": "airflow",
    "retries": 1,
    "retry_delay": timedelta(minutes=3),
    "execution_timeout": timedelta(hours=1),
}


with DAG(
    dag_id="daily_tracker_dag",
    default_args=default_args,
    description="Daily tracker and followup DAG.",
    schedule="0 8 * * *",
    start_date=datetime(2024, 1, 1, tzinfo=timezone.utc),
    catchup=False,
    max_active_runs=1,
    tags=["tracker", "daily"],
) as dag:
    task_check_followup_queue = PythonOperator(
        task_id="task_check_followup_queue",
        python_callable=check_followup_queue,
    )

    task_send_followups = PythonOperator(
        task_id="task_send_followups",
        python_callable=send_due_followups,
    )

    task_check_daily_limit = PythonOperator(
        task_id="task_check_daily_limit",
        python_callable=check_daily_limit,
    )

    task_scan_stale_leads = PythonOperator(
        task_id="task_scan_stale_leads",
        python_callable=scan_stale_leads,
    )

    task_update_sequence_completions = PythonOperator(
        task_id="task_update_sequence_completions",
        python_callable=update_sequence_completions,
    )

    task_send_daily_summary = PythonOperator(
        task_id="task_send_daily_summary",
        python_callable=send_daily_summary,
    )

    task_check_followup_queue.set_downstream(task_send_followups)
    task_send_followups.set_downstream(task_check_daily_limit)
    task_check_daily_limit.set_downstream(task_scan_stale_leads)
    task_scan_stale_leads.set_downstream(task_update_sequence_completions)
    task_update_sequence_completions.set_downstream(task_send_daily_summary)
