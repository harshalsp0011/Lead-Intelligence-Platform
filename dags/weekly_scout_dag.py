from __future__ import annotations

"""Weekly Airflow DAG for scheduled scout discovery and analyst handoff.

Purpose:
- Runs the scout workflow every Monday morning, validates the weekly batch,
  notifies Slack, and kicks off analyst scoring for the newly found companies.

Dependencies:
- `airflow` for DAG and PythonOperator definitions.
- `database.connection.SessionLocal` for PostgreSQL sessions.
- `agents.orchestrator.orchestrator` for scout and analyst execution.
- `config.settings.get_settings` plus optional env vars for weekly target config.

Usage:
- Place this file in Airflow's DAGs folder and ensure the project root is
  importable.
- Configure optional weekly target values with `TARGET_INDUSTRIES`,
  `TARGET_LOCATIONS`, and `SCOUT_WEEKLY_TARGET_COUNT`.
"""

import logging
import sys
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

import requests
from airflow import DAG
from airflow.operators.python import PythonOperator
from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

from agents.orchestrator import orchestrator
from config.settings import get_settings
from database.connection import SessionLocal

logger = logging.getLogger(__name__)

SCOUT_CONFIG_XCOM_KEY = "scout_config"
REMAINING_COUNT_XCOM_KEY = "remaining_count"
NEW_COMPANY_IDS_XCOM_KEY = "new_company_ids"
VALIDATED_COMPANY_IDS_XCOM_KEY = "validated_company_ids"
SCORED_COMPANY_IDS_XCOM_KEY = "scored_company_ids"


@contextmanager
def db_session_scope() -> Iterator[Session]:
    """Yield a DB session and always close it after task execution."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def _read_setting_value(settings: Any, *names: str, default: Any = None) -> Any:
    """Read a config value from settings only, falling back to the provided default."""
    for name in names:
        value = getattr(settings, name, None)
        if value not in (None, ""):
            return value

    return default


def _normalize_setting_list(raw_value: Any, default: list[str]) -> list[str]:
    """Normalize comma-delimited or iterable config values into a clean list."""
    if raw_value is None:
        values = list(default)
    elif isinstance(raw_value, str):
        values = [item.strip() for item in raw_value.split(",") if item.strip()]
    elif isinstance(raw_value, (list, tuple, set)):
        values = [str(item).strip() for item in raw_value if str(item).strip()]
    else:
        values = [str(raw_value).strip()] if str(raw_value).strip() else []

    return values or list(default)


def _normalize_filter_values(values: list[str]) -> list[str]:
    """Return normalized values used for SQL filtering and scout dispatch."""
    normalized = []
    for value in values:
        candidate = str(value).strip()
        if not candidate or candidate.lower() in {"all", "*"}:
            continue
        normalized.append(candidate.lower())
    return normalized


def _normalize_display_values(values: list[str]) -> list[str]:
    """Return values for log and Slack display."""
    display_values = [str(value).strip() for value in values if str(value).strip()]
    return display_values or ["all"]


def _read_target_count(settings: Any) -> int:
    """Return the configured weekly scout target count."""
    raw_value = _read_setting_value(
        settings,
        "SCOUT_WEEKLY_TARGET_COUNT",
        "SCOUT_TARGET_COUNT",
        default=settings.SCOUT_WEEKLY_TARGET_COUNT,
    )
    try:
        return max(int(raw_value), 0)
    except (TypeError, ValueError):
        logger.warning("Invalid weekly scout target count %r; using settings default", raw_value)
        return int(settings.SCOUT_WEEKLY_TARGET_COUNT)


def _coerce_logical_date(value: Any) -> datetime:
    """Convert Airflow logical_date values into a timezone-aware datetime."""
    if isinstance(value, datetime):
        logical_date = value
    else:
        logical_date = datetime.now(timezone.utc)

    if logical_date.tzinfo is None:
        logical_date = logical_date.replace(tzinfo=timezone.utc)

    return logical_date


def _current_week_start(context: dict[str, Any]) -> datetime:
    """Return the Monday 00:00 timestamp for the current logical week."""
    logical_date = _coerce_logical_date(context.get("logical_date"))
    week_start = logical_date - timedelta(days=logical_date.weekday())
    return week_start.replace(hour=0, minute=0, second=0, microsecond=0)


def _build_existing_count_query(
    industries: list[str],
    locations: list[str],
) -> tuple[Any, dict[str, Any]]:
    """Build the weekly company count query for the configured filters."""
    sql_lines = [
        """
        SELECT COUNT(*)
        FROM companies
        WHERE COALESCE(date_found, created_at) >= :week_start
        """.strip()
    ]
    params: dict[str, Any] = {}
    bind_params = []

    if industries:
        sql_lines.append("AND LOWER(COALESCE(industry, '')) IN :industries")
        params["industries"] = industries
        bind_params.append(bindparam("industries", expanding=True))

    if locations:
        sql_lines.append(
            "AND LOWER(TRIM(CONCAT(COALESCE(city, ''), ', ', COALESCE(state, '')))) IN :locations"
        )
        params["locations"] = locations
        bind_params.append(bindparam("locations", expanding=True))

    query = text("\n".join(sql_lines))
    if bind_params:
        query = query.bindparams(*bind_params)

    return query, params


def _build_search_plan(
    industries: list[str],
    locations: list[str],
    remaining_count: int,
) -> list[tuple[str, str, int]]:
    """Split the remaining target across industry/location combinations."""
    if remaining_count <= 0:
        return []

    industry_values = industries or ["all"]
    location_values = locations or ["all"]
    combinations = [(industry, location) for industry in industry_values for location in location_values]

    plan: list[tuple[str, str, int]] = []
    outstanding = remaining_count
    combos_left = len(combinations)

    for industry, location in combinations:
        if outstanding <= 0:
            break

        planned_count = max(1, (outstanding + combos_left - 1) // combos_left)
        plan.append((industry, location, planned_count))
        outstanding -= planned_count
        combos_left -= 1

    return plan


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


def load_target_config(**context: Any) -> dict[str, Any]:
    """Load weekly scout target filters and share them via XCom."""
    settings = get_settings()
    industries = _normalize_setting_list(
        _read_setting_value(settings, "TARGET_INDUSTRIES", "SCOUT_TARGET_INDUSTRIES"),
        default=["all"],
    )
    locations = _normalize_setting_list(
        _read_setting_value(settings, "TARGET_LOCATIONS", "SCOUT_TARGET_LOCATIONS"),
        default=["all"],
    )
    target_count = _read_target_count(settings)

    config = {
        "industries": _normalize_display_values(industries),
        "locations": _normalize_display_values(locations),
        "target_count": target_count,
    }

    task_instance = context["ti"]
    task_instance.xcom_push(key=SCOUT_CONFIG_XCOM_KEY, value=config)
    task_instance.xcom_push(key="industries", value=config["industries"])
    task_instance.xcom_push(key="locations", value=config["locations"])
    return config


def check_existing_counts(**context: Any) -> dict[str, Any]:
    """Count companies already found this week and compute remaining target."""
    task_instance = context["ti"]
    config = task_instance.xcom_pull(task_ids="task_load_config", key=SCOUT_CONFIG_XCOM_KEY) or {}
    industries = _normalize_filter_values(list(config.get("industries", [])))
    locations = _normalize_filter_values(list(config.get("locations", [])))
    target_count = int(config.get("target_count", 0) or 0)
    week_start = _current_week_start(context)

    query, params = _build_existing_count_query(industries, locations)
    params["week_start"] = week_start

    with db_session_scope() as db_session:
        existing_count = int(db_session.execute(query, params).scalar_one() or 0)

    remaining_count = max(target_count - existing_count, 0)
    result = {
        "week_start": week_start.isoformat(),
        "existing_count": existing_count,
        "target_count": target_count,
        "remaining_count": remaining_count,
    }

    task_instance.xcom_push(key=REMAINING_COUNT_XCOM_KEY, value=remaining_count)
    return result


def run_scout_task(**context: Any) -> list[str]:
    """Run scout searches for the configured weekly targets and collect IDs."""
    task_instance = context["ti"]
    config = task_instance.xcom_pull(task_ids="task_load_config", key=SCOUT_CONFIG_XCOM_KEY) or {}
    remaining_count = int(
        task_instance.xcom_pull(
            task_ids="task_check_existing",
            key=REMAINING_COUNT_XCOM_KEY,
        )
        or 0
    )

    industries = list(config.get("industries", []))
    locations = list(config.get("locations", []))
    search_plan = _build_search_plan(industries, locations, remaining_count)
    new_company_ids: list[str] = []

    if not search_plan:
        task_instance.xcom_push(key=NEW_COMPANY_IDS_XCOM_KEY, value=new_company_ids)
        return new_company_ids

    with db_session_scope() as db_session:
        for industry, location, planned_count in search_plan:
            if planned_count <= 0:
                continue

            scout_result = orchestrator.run_scout(
                industry="" if industry.lower() == "all" else industry,
                location="" if location.lower() == "all" else location,
                count=planned_count,
                db_session=db_session,
            )
            discovered_ids = list(scout_result.get("company_ids", []))
            if discovered_ids:
                new_company_ids.extend(str(company_id) for company_id in discovered_ids)

        db_session.commit()

    deduplicated_ids = list(dict.fromkeys(new_company_ids))
    task_instance.xcom_push(key=NEW_COMPANY_IDS_XCOM_KEY, value=deduplicated_ids)
    return deduplicated_ids


def validate_scout_results(**context: Any) -> list[str]:
    """Validate newly found companies and alert when the batch is too small."""
    task_instance = context["ti"]
    company_ids = list(
        task_instance.xcom_pull(task_ids="task_run_scout", key=NEW_COMPANY_IDS_XCOM_KEY)
        or []
    )
    validated_ids = [str(company_id) for company_id in company_ids if str(company_id).strip()]

    if len(validated_ids) < 5:
        _send_slack_message(
            "Weekly Scout Alert\n"
            f"Only {len(validated_ids)} companies were found in this run.\n"
            "Review scout sources and target configuration."
        )

    task_instance.xcom_push(key=VALIDATED_COMPANY_IDS_XCOM_KEY, value=validated_ids)
    return validated_ids


def notify_scout_complete(**context: Any) -> int:
    """Send the weekly scout completion summary to Slack."""
    task_instance = context["ti"]
    config = task_instance.xcom_pull(task_ids="task_load_config", key=SCOUT_CONFIG_XCOM_KEY) or {}
    company_ids = list(
        task_instance.xcom_pull(
            task_ids="task_validate_results",
            key=VALIDATED_COMPANY_IDS_XCOM_KEY,
        )
        or []
    )

    industries = ", ".join(config.get("industries", ["all"]))
    locations = ", ".join(config.get("locations", ["all"]))
    count = len(company_ids)

    message = (
        "Weekly Scout Complete\n"
        f"Companies found this run: {count}\n"
        f"Industries searched: {industries}\n"
        f"Locations searched: {locations}\n"
        "View dashboard: http://localhost:3000"
    )
    _send_slack_message(message)
    return count


def _fetch_scored_company_ids(company_ids: list[str], db_session: Session) -> list[str]:
    """Return the company IDs that have score rows after analyst execution."""
    if not company_ids:
        return []

    query = text(
        """
        SELECT DISTINCT ls.company_id
        FROM lead_scores ls
        WHERE ls.company_id IN :company_ids
        ORDER BY ls.company_id
        """.strip()
    ).bindparams(bindparam("company_ids", expanding=True))

    rows = db_session.execute(query, {"company_ids": company_ids}).scalars().all()
    return [str(company_id) for company_id in rows]


def trigger_analyst_dag(**context: Any) -> list[str]:
    """Run analyst scoring for the validated scout companies."""
    task_instance = context["ti"]
    company_ids = list(
        task_instance.xcom_pull(
            task_ids="task_validate_results",
            key=VALIDATED_COMPANY_IDS_XCOM_KEY,
        )
        or []
    )

    with db_session_scope() as db_session:
        orchestrator.run_analyst(company_ids, db_session)
        scored_ids = _fetch_scored_company_ids(company_ids, db_session)

    task_instance.xcom_push(key=SCORED_COMPANY_IDS_XCOM_KEY, value=scored_ids)
    logger.info("Analyst triggered for %d companies", len(company_ids))
    return scored_ids


default_args = {
    "owner": "airflow",
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
    "email_on_failure": False,
    "execution_timeout": timedelta(hours=2),
}


with DAG(
    dag_id="weekly_scout_dag",
    default_args=default_args,
    description="Weekly scout discovery DAG with analyst handoff.",
    schedule="0 9 * * 1",
    start_date=datetime(2024, 1, 1, tzinfo=timezone.utc),
    catchup=False,
    max_active_runs=1,
    tags=["scout", "weekly"],
) as dag:
    task_load_config = PythonOperator(
        task_id="task_load_config",
        python_callable=load_target_config,
    )

    task_check_existing = PythonOperator(
        task_id="task_check_existing",
        python_callable=check_existing_counts,
    )

    task_run_scout = PythonOperator(
        task_id="task_run_scout",
        python_callable=run_scout_task,
    )

    task_validate_results = PythonOperator(
        task_id="task_validate_results",
        python_callable=validate_scout_results,
    )

    task_notify_scout_complete = PythonOperator(
        task_id="task_notify_scout_complete",
        python_callable=notify_scout_complete,
    )

    task_trigger_analyst = PythonOperator(
        task_id="task_trigger_analyst",
        python_callable=trigger_analyst_dag,
    )

    task_load_config.set_downstream(task_check_existing)
    task_check_existing.set_downstream(task_run_scout)
    task_run_scout.set_downstream(task_validate_results)
    task_validate_results.set_downstream(task_notify_scout_complete)
    task_notify_scout_complete.set_downstream(task_trigger_analyst)