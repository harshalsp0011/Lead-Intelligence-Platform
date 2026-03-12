from __future__ import annotations

"""Daily Airflow DAG for analyst scoring, enrichment, and writer handoff.

Purpose:
- Runs daily to score unscored companies, enrich high-tier leads with contacts,
  check pipeline value, and hand off approved leads to writer.

Dependencies:
- `airflow` for DAG and PythonOperator definitions.
- `database.connection.SessionLocal` for PostgreSQL sessions.
- `agents.orchestrator.orchestrator` for analyst, enrichment, and writer execution.
- `agents.analyst.enrichment_client` for contact discovery.
- `config.settings.get_settings` for Slack webhook and contingency fee config.

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

import requests
from airflow import DAG
from airflow.providers.standard.operators.python import PythonOperator
from sqlalchemy import text
from sqlalchemy.orm import Session

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

from agents.analyst import enrichment_client
from agents.orchestrator import orchestrator
from config.settings import get_settings
from database.connection import SessionLocal

logger = logging.getLogger(__name__)

UNSCORED_COMPANY_IDS_XCOM_KEY = "unscored_company_ids"
ANALYST_RESULTS_XCOM_KEY = "analyst_results"
HIGH_SCORE_COMPANY_IDS_XCOM_KEY = "high_score_company_ids"
ENRICHMENT_CONTACT_COUNT_XCOM_KEY = "enrichment_contact_count"
PIPELINE_VALUE_XCOM_KEY = "pipeline_value"
PENDING_APPROVAL_COUNT_XCOM_KEY = "pending_approval_count"


@contextmanager
def db_session_scope() -> Iterator[Session]:
    """Yield a DB session and always close it after task execution."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def _send_slack_message(message: str) -> bool:
    """Post a plain-text Slack message when a webhook is configured."""
    settings = get_settings()
    webhook_url = str(getattr(settings, "SLACK_WEBHOOK_URL", "") or "").strip()
    if not webhook_url:
        logger.warning("Slack webhook not configured. Message was: %s", message)
        return False

    try:
        response = requests.post(webhook_url, json={"text": message}, timeout=10)
        response.raise_for_status()
        return True
    except requests.RequestException:
        logger.exception("Failed to send Slack message")
        return False


def _format_currency(value: float) -> str:
    """Format a number as a currency string."""
    if value < 0:
        return f"-${abs(value):,.0f}"
    return f"${value:,.0f}"


def _calculate_pipeline_value(db_session: Session) -> dict[str, Any]:
    """Fetch high-tier pipeline value metrics."""
    row = db_session.execute(
        text(
            """
            SELECT
                COUNT(DISTINCT c.id) AS total_leads_high,
                COALESCE(SUM(cf.savings_low), 0) AS total_savings_low,
                COALESCE(SUM(cf.savings_mid), 0) AS total_savings_mid,
                COALESCE(SUM(cf.savings_high), 0) AS total_savings_high
            FROM companies c
            JOIN lead_scores ls
                ON ls.company_id = c.id
            JOIN company_features cf
                ON cf.company_id = c.id
            WHERE ls.tier = 'high'
              AND COALESCE(c.status, '') NOT IN ('lost', 'archived', 'no_response')
            """.strip()
        )
    ).mappings().first()

    total_leads_high = int((row or {}).get("total_leads_high") or 0)
    total_savings_mid = float((row or {}).get("total_savings_mid") or 0.0)

    settings = get_settings()
    contingency_fee = float(getattr(settings, "TB_CONTINGENCY_FEE", 0.24) or 0.24)
    total_tb_revenue_est = total_savings_mid * contingency_fee

    return {
        "total_leads_high": total_leads_high,
        "total_savings_mid": total_savings_mid,
        "total_tb_revenue_est": total_tb_revenue_est,
    }


def _count_pending_approval(db_session: Session) -> int:
    """Count high-tier leads waiting human approval."""
    result = db_session.execute(
        text(
            """
            SELECT COUNT(DISTINCT ls.company_id)
            FROM lead_scores ls
            WHERE ls.tier = 'high'
              AND COALESCE(ls.approved_human, false) = false
            """.strip()
        )
    ).scalar_one()
    return int(result or 0)


def fetch_unscored_companies(**context: Any) -> list[str]:
    """Fetch companies marked as new or enriched for scoring."""
    with db_session_scope() as db_session:
        rows = db_session.execute(
            text(
                """
                SELECT id
                FROM companies
                WHERE COALESCE(status, 'new') IN ('new', 'enriched')
                ORDER BY created_at ASC
                LIMIT 1000
                """.strip()
            )
        ).scalars().all()

        company_ids = [str(company_id) for company_id in rows]

    task_instance = context["ti"]
    task_instance.xcom_push(key=UNSCORED_COMPANY_IDS_XCOM_KEY, value=company_ids)

    logger.info("Found %d unscored companies", len(company_ids))
    return company_ids


def run_analyst_task(**context: Any) -> dict[str, int]:
    """Run analyst scoring on unscored companies."""
    task_instance = context["ti"]
    company_ids = list(
        task_instance.xcom_pull(
            task_ids="task_fetch_unscored",
            key=UNSCORED_COMPANY_IDS_XCOM_KEY,
        )
        or []
    )

    if not company_ids:
        result = {"scored": 0, "high": 0, "medium": 0, "low": 0}
        task_instance.xcom_push(key=ANALYST_RESULTS_XCOM_KEY, value=result)
        return result

    with db_session_scope() as db_session:
        analyst_result = orchestrator.run_analyst(company_ids, db_session)

    scored = int(analyst_result.get("scored", 0) or 0)
    high = int(analyst_result.get("high", 0) or 0)
    medium = int(analyst_result.get("medium", 0) or 0)
    low = int(analyst_result.get("low", 0) or 0)

    result = {
        "scored": scored,
        "high": high,
        "medium": medium,
        "low": low,
    }
    task_instance.xcom_push(key=ANALYST_RESULTS_XCOM_KEY, value=result)
    return result


def filter_high_score_leads(**context: Any) -> list[str]:
    """Query high-tier leads scored today that lack human approval."""
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

    with db_session_scope() as db_session:
        rows = db_session.execute(
            text(
                """
                SELECT DISTINCT ls.company_id
                FROM lead_scores ls
                WHERE ls.tier = 'high'
                  AND COALESCE(ls.approved_human, false) = false
                  AND ls.scored_at >= :today_start
                ORDER BY ls.scored_at DESC
                """.strip()
            ),
            {"today_start": today_start},
        ).scalars().all()

        company_ids = [str(company_id) for company_id in rows]

    task_instance = context["ti"]
    task_instance.xcom_push(key=HIGH_SCORE_COMPANY_IDS_XCOM_KEY, value=company_ids)

    return company_ids


def run_contact_enrichment(**context: Any) -> int:
    """Enrich high-score companies with contact discovery."""
    task_instance = context["ti"]
    company_ids = list(
        task_instance.xcom_pull(
            task_ids="task_filter_high_score",
            key=HIGH_SCORE_COMPANY_IDS_XCOM_KEY,
        )
        or []
    )

    if not company_ids:
        task_instance.xcom_push(key=ENRICHMENT_CONTACT_COUNT_XCOM_KEY, value=0)
        return 0

    total_contacts = 0

    with db_session_scope() as db_session:
        rows = db_session.execute(
            text(
                """
                SELECT id, name, website
                FROM companies
                WHERE id IN :company_ids
                """.strip()
            ),
            {"company_ids": company_ids},
        ).mappings().all()

        for row in rows:
            company_id = str(row.get("id") or "")
            name = str(row.get("name") or "")
            website = str(row.get("website") or "")

            try:
                contacts = enrichment_client.find_contacts(
                    company_name=name,
                    website_domain=website,
                    db_session=db_session,
                )
                total_contacts += len(contacts)
            except Exception:
                logger.exception(
                    "Contact enrichment failed for company_id=%s",
                    company_id,
                )

    task_instance.xcom_push(key=ENRICHMENT_CONTACT_COUNT_XCOM_KEY, value=total_contacts)
    logger.info("Found %d contacts for high-score leads", total_contacts)
    return total_contacts


def notify_analyst_complete(**context: Any) -> None:
    """Send daily analyst completion summary to Slack."""
    task_instance = context["ti"]

    analyst_results = (
        task_instance.xcom_pull(
            task_ids="task_run_analyst",
            key=ANALYST_RESULTS_XCOM_KEY,
        )
        or {}
    )
    contact_count = int(
        task_instance.xcom_pull(
            task_ids="task_run_enrichment",
            key=ENRICHMENT_CONTACT_COUNT_XCOM_KEY,
        )
        or 0
    )

    scored = int(analyst_results.get("scored", 0) or 0)
    high = int(analyst_results.get("high", 0) or 0)
    medium = int(analyst_results.get("medium", 0) or 0)
    low = int(analyst_results.get("low", 0) or 0)

    with db_session_scope() as db_session:
        pipeline_value = _calculate_pipeline_value(db_session)
        pending = _count_pending_approval(db_session)

    total_value = float(pipeline_value.get("total_tb_revenue_est", 0.0) or 0.0)
    value_formatted = _format_currency(total_value)

    message = (
        "Daily Analyst Complete\n"
        f"Companies scored: {scored}\n"
        f"High score leads: {high}\n"
        f"Medium score leads: {medium}\n"
        f"Low score leads: {low}\n"
        f"Contacts found: {contact_count}\n"
        f"Total pipeline value: {value_formatted}\n"
        f"Leads awaiting approval: {pending}\n"
        "Review now: http://localhost:3000/leads"
    )
    _send_slack_message(message)

    task_instance.xcom_push(key=PIPELINE_VALUE_XCOM_KEY, value=pipeline_value)
    task_instance.xcom_push(key=PENDING_APPROVAL_COUNT_XCOM_KEY, value=pending)


def trigger_writer_task(**context: Any) -> None:
    """Run writer stage for approved high-tier leads with no email draft."""
    with db_session_scope() as db_session:
        rows = db_session.execute(
            text(
                """
                SELECT ls.company_id
                FROM lead_scores ls
                WHERE ls.tier = 'high'
                  AND COALESCE(ls.approved_human, false) = true
                  AND NOT EXISTS (
                      SELECT 1
                      FROM email_drafts ed
                      WHERE ed.company_id = ls.company_id
                  )
                ORDER BY ls.scored_at DESC
                """.strip()
            )
        ).scalars().all()

        approved_ids = [str(company_id) for company_id in rows]

        if approved_ids:
            orchestrator.run_writer(db_session)
            logger.info("Writer triggered for %d approved leads", len(approved_ids))
        else:
            logger.info("No approved leads ready for writing")


default_args = {
    "owner": "airflow",
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
    "execution_timeout": timedelta(hours=3),
}


with DAG(
    dag_id="daily_analyst_dag",
    default_args=default_args,
    description="Daily analyst scoring, enrichment, and writer handoff DAG.",
    schedule="0 10 * * *",
    start_date=datetime(2024, 1, 1, tzinfo=timezone.utc),
    catchup=False,
    max_active_runs=1,
    tags=["analyst", "daily"],
) as dag:
    task_fetch_unscored = PythonOperator(
        task_id="task_fetch_unscored",
        python_callable=fetch_unscored_companies,
    )

    task_run_analyst = PythonOperator(
        task_id="task_run_analyst",
        python_callable=run_analyst_task,
    )

    task_filter_high_score = PythonOperator(
        task_id="task_filter_high_score",
        python_callable=filter_high_score_leads,
    )

    task_run_enrichment = PythonOperator(
        task_id="task_run_enrichment",
        python_callable=run_contact_enrichment,
    )

    task_notify_analyst_complete = PythonOperator(
        task_id="task_notify_analyst_complete",
        python_callable=notify_analyst_complete,
    )

    task_trigger_writer = PythonOperator(
        task_id="task_trigger_writer",
        python_callable=trigger_writer_task,
    )

    task_fetch_unscored.set_downstream(task_run_analyst)
    task_run_analyst.set_downstream(task_filter_high_score)
    task_filter_high_score.set_downstream(task_run_enrichment)
    task_run_enrichment.set_downstream(task_notify_analyst_complete)
    task_notify_analyst_complete.set_downstream(task_trigger_writer)
