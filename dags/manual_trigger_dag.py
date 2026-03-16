from __future__ import annotations

"""Manual trigger Airflow DAG for on-demand pipeline execution.

Purpose:
- Allows operators to manually trigger specific pipeline stages (full, scout,
  analyst, or writer) with custom parameters and validated inputs.

Dependencies:
- `airflow` for DAG, PythonOperator, and Param definitions.
- `database.connection.SessionLocal` for PostgreSQL sessions.
- `agents.orchestrator.orchestrator` for stage execution.
- `config.settings.get_settings` for Slack webhook configuration.

Usage:
- Trigger manually from Airflow UI with params: industry, location, count, run_mode.
- Or pass params via `dag_run.conf` in API calls.
"""

import json
import logging
import sys
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

import requests
from airflow import DAG
from airflow.models import Param
from airflow.operators.python import PythonOperator
from sqlalchemy import select
from sqlalchemy.orm import Session

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

from agents.orchestrator import orchestrator
from config.settings import get_settings
from database.connection import SessionLocal
from database.orm_models import Company

logger = logging.getLogger(__name__)

VALIDATED_PARAMS_XCOM_KEY = "validated_params"
RESULTS_XCOM_KEY = "results"
DURATION_SECONDS_XCOM_KEY = "duration_seconds"

_VALID_INDUSTRIES = {"healthcare", "hospitality", "manufacturing", "retail", "public_sector", "office"}
_VALID_RUN_MODES = {"full", "scout_only", "analyst_only", "writer_only"}


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


def _ensure_logs_folder() -> Path:
    """Create logs folder if it doesn't exist."""
    logs_dir = PROJECT_ROOT / "logs"
    logs_dir.mkdir(exist_ok=True)
    return logs_dir


def _format_result_summary(result: dict[str, Any]) -> str:
    """Build a human-readable summary of pipeline results."""
    if isinstance(result, dict):
        items = []
        for key, value in result.items():
            if isinstance(value, (int, str)):
                items.append(f"{key}: {value}")
        return ", ".join(items) if items else "completed"
    return str(result)


def validate_trigger_inputs(**context: Any) -> dict[str, Any]:
    """Validate and normalize manual trigger parameters."""
    dag_run = context.get("dag_run")
    params = {}

    if dag_run and dag_run.conf:
        params.update(dag_run.conf)

    task_instance = context["ti"]
    params.update(task_instance.dag_run.params or {})

    industry = str(params.get("industry", "healthcare")).strip().lower()
    location = str(params.get("location", "")).strip()
    count = int(params.get("count", 20) or 20)
    run_mode = str(params.get("run_mode", "full")).strip().lower()

    errors = []

    if industry not in _VALID_INDUSTRIES:
        errors.append(
            f"Invalid industry '{industry}'. Must be one of: {', '.join(sorted(_VALID_INDUSTRIES))}"
        )

    if not location:
        errors.append("Location cannot be empty")

    if count < 5 or count > 100:
        errors.append("Count must be between 5 and 100")

    if run_mode not in _VALID_RUN_MODES:
        errors.append(
            f"Invalid run_mode '{run_mode}'. Must be one of: {', '.join(sorted(_VALID_RUN_MODES))}"
        )

    if errors:
        error_msg = "; ".join(errors)
        logger.error("Validation failed: %s", error_msg)
        raise ValueError(f"Validation failed: {error_msg}")

    validated = {
        "industry": industry,
        "location": location,
        "count": count,
        "run_mode": run_mode,
    }

    task_instance.xcom_push(key=VALIDATED_PARAMS_XCOM_KEY, value=validated)
    logger.info("Inputs validated: %s", validated)
    return validated


def run_selected_mode(**context: Any) -> dict[str, Any]:
    """Execute the selected pipeline mode with validated parameters."""
    start_time = datetime.now(timezone.utc)

    task_instance = context["ti"]
    validated_params = (
        task_instance.xcom_pull(
            task_ids="task_validate_inputs",
            key=VALIDATED_PARAMS_XCOM_KEY,
        )
        or {}
    )

    industry = str(validated_params.get("industry", "")).strip()
    location = str(validated_params.get("location", "")).strip()
    count = int(validated_params.get("count", 0) or 0)
    run_mode = str(validated_params.get("run_mode", "")).strip()

    result = {}

    with db_session_scope() as db_session:
        if run_mode == "full":
            result = orchestrator.run_full_pipeline(industry, location, count, db_session)
            logger.info("Full pipeline completed: %s", result)

        elif run_mode == "scout_only":
            scout_result = orchestrator.run_scout(industry, location, count, db_session)
            result = {"stage": "scout", "company_ids": scout_result.get("company_ids", [])}
            logger.info("Scout stage completed: found %d companies", len(result.get("company_ids", [])))

        elif run_mode == "analyst_only":
            unscored_rows = db_session.execute(
                select(Company.id)
                .where((Company.status.is_(None)) | (Company.status.in_(["new", "enriched"])))
                .limit(500)
            ).scalars().all()
            unscored_ids = [str(company_id) for company_id in unscored_rows]

            analyst_result = orchestrator.run_analyst(unscored_ids, db_session)
            result = {
                "stage": "analyst",
                "companies_scored": analyst_result.get("scored", 0),
                "high_tier": analyst_result.get("high", 0),
                "medium_tier": analyst_result.get("medium", 0),
                "low_tier": analyst_result.get("low", 0),
            }
            logger.info("Analyst stage completed: %s", result)

        elif run_mode == "writer_only":
            writer_result = orchestrator.run_writer(db_session)
            result = {
                "stage": "writer",
                "drafts_created": writer_result.get("drafts_created", 0),
            }
            logger.info("Writer stage completed: %s", result)

    end_time = datetime.now(timezone.utc)
    duration_seconds = int((end_time - start_time).total_seconds())

    task_instance.xcom_push(key=RESULTS_XCOM_KEY, value=result)
    task_instance.xcom_push(key=DURATION_SECONDS_XCOM_KEY, value=duration_seconds)

    return result


def log_manual_trigger(**context: Any) -> None:
    """Write trigger event to manual_triggers.txt log file."""
    task_instance = context["ti"]

    validated_params = (
        task_instance.xcom_pull(
            task_ids="task_validate_inputs",
            key=VALIDATED_PARAMS_XCOM_KEY,
        )
        or {}
    )
    result = (
        task_instance.xcom_pull(
            task_ids="task_run_selected_mode",
            key=RESULTS_XCOM_KEY,
        )
        or {}
    )
    duration_seconds = int(
        task_instance.xcom_pull(
            task_ids="task_run_selected_mode",
            key=DURATION_SECONDS_XCOM_KEY,
        )
        or 0
    )

    task_instance = context.get("task_instance")
    triggered_by = str(getattr(task_instance, "task_id", "unknown") or "unknown")
    dag_run = context.get("dag_run")
    triggered_by_user = str(getattr(dag_run, "triggering_dag_id", "manual") or "manual").strip()

    logs_dir = _ensure_logs_folder()
    log_file = logs_dir / "manual_triggers.txt"

    timestamp = datetime.now(timezone.utc).isoformat()
    result_summary = _format_result_summary(result)

    log_entry = {
        "timestamp": timestamp,
        "triggered_by": triggered_by_user,
        "industry": validated_params.get("industry"),
        "location": validated_params.get("location"),
        "count": validated_params.get("count"),
        "run_mode": validated_params.get("run_mode"),
        "duration_seconds": duration_seconds,
        "result_summary": result_summary,
    }

    try:
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(log_entry) + "\n")
        logger.info("Logged manual trigger to %s", log_file)
    except Exception:
        logger.exception("Failed to write manual trigger log")


def notify_trigger_complete(**context: Any) -> bool:
    """Send completion notification to Slack."""
    task_instance = context["ti"]

    validated_params = (
        task_instance.xcom_pull(
            task_ids="task_validate_inputs",
            key=VALIDATED_PARAMS_XCOM_KEY,
        )
        or {}
    )
    result = (
        task_instance.xcom_pull(
            task_ids="task_run_selected_mode",
            key=RESULTS_XCOM_KEY,
        )
        or {}
    )
    duration_seconds = int(
        task_instance.xcom_pull(
            task_ids="task_run_selected_mode",
            key=DURATION_SECONDS_XCOM_KEY,
        )
        or 0
    )

    industry = validated_params.get("industry", "unknown")
    location = validated_params.get("location", "unknown")
    run_mode = validated_params.get("run_mode", "unknown")
    result_summary = _format_result_summary(result)

    message = (
        "Manual Pipeline Run Complete\n"
        f"Mode: {run_mode}\n"
        f"Industry: {industry}\n"
        f"Location: {location}\n"
        f"Results: {result_summary}\n"
        f"Duration: {duration_seconds}s\n"
        "View results: http://localhost:3000"
    )

    return _send_slack_message(message)


default_args = {
    "owner": "airflow",
    "retries": 1,
    "retry_delay": timedelta(minutes=2),
    "execution_timeout": timedelta(hours=4),
}


with DAG(
    dag_id="manual_trigger_dag",
    default_args=default_args,
    description="Manual on-demand pipeline trigger DAG.",
    schedule=None,
    start_date=datetime(2024, 1, 1, tzinfo=timezone.utc),
    catchup=False,
    max_active_runs=3,
    tags=["manual", "on-demand"],
    params={
        "industry": Param(default="healthcare", type="string"),
        "location": Param(default="Buffalo, NY", type="string"),
        "count": Param(default=20, type="integer"),
        "run_mode": Param(default="full", type="string"),
    },  # type: ignore[arg-type]
) as dag:
    task_validate_inputs = PythonOperator(
        task_id="task_validate_inputs",
        python_callable=validate_trigger_inputs,
    )

    task_run_selected_mode = PythonOperator(
        task_id="task_run_selected_mode",
        python_callable=run_selected_mode,
    )

    task_log_trigger = PythonOperator(
        task_id="task_log_trigger",
        python_callable=log_manual_trigger,
    )

    task_notify_complete = PythonOperator(
        task_id="task_notify_complete",
        python_callable=notify_trigger_complete,
    )

    task_validate_inputs.set_downstream(task_run_selected_mode)
    task_run_selected_mode.set_downstream(task_log_trigger)
    task_log_trigger.set_downstream(task_notify_complete)
