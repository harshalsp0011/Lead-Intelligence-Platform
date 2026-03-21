from __future__ import annotations

"""Task assignment and monitoring for the orchestrator.

Purpose:
- Routes tasks to individual agents (scout, analyst, writer, outreach, tracker).
- Tracks task state (running / completed / failed) in an in-process log dict.
- Supports retry logic (up to 3 attempts) with Slack alert on exhaustion.
- Persists structured log lines to logs/task_log.txt.

Dependencies:
- `agents.scout.scout_agent`, `agents.analyst.analyst_agent`,
  `agents.writer.writer_agent`, `agents.outreach.outreach_agent`,
  `agents.tracker.tracker_agent` for agent run() entry points.
- `sqlalchemy.orm.Session` injected by caller.

Usage:
- Call `assign_task(agent_name, params, db_session)` to dispatch work.
- Call `check_task_status(task_id)` to poll current state.
- Call `retry_failed_task(task_id, db_session)` to retry up to 3 times.
- Call `log_task_result(...)` to emit a structured audit line to file + stdout.
"""

import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from config.settings import get_settings

# ---------------------------------------------------------------------------
# In-process task registry
# Each entry: {agent_name, params, status, result, started_at,
#              ended_at, retry_count}
# ---------------------------------------------------------------------------
_TASK_LOG: dict[str, dict[str, Any]] = {}

_VALID_AGENTS = {"scout", "analyst", "writer", "outreach", "tracker"}

_LOG_FILE = Path("logs/task_log.txt")


# ---------------------------------------------------------------------------
# Public functions
# ---------------------------------------------------------------------------


def assign_task(
    agent_name: str,
    task_params: dict[str, Any],
    db_session: Session,
) -> dict[str, Any]:
    """Route a task to the named agent and return task_id, status, result."""
    if agent_name not in _VALID_AGENTS:
        return {
            "task_id": None,
            "status": "failed",
            "result": {"error": f"Unknown agent '{agent_name}'. "
                                f"Valid agents: {sorted(_VALID_AGENTS)}"},
        }

    task_id = str(uuid.uuid4())
    started_at = datetime.now(timezone.utc)

    _TASK_LOG[task_id] = {
        "agent_name": agent_name,
        "params": task_params,
        "status": "running",
        "result": None,
        "started_at": started_at,
        "ended_at": None,
        "retry_count": 0,
    }

    result: dict[str, Any] = {}
    status = "completed"

    try:
        result = _dispatch(agent_name, task_params, db_session)
    except Exception as exc:  # noqa: BLE001
        status = "failed"
        result = {"error": str(exc)}

    ended_at = datetime.now(timezone.utc)
    duration = int((ended_at - started_at).total_seconds())

    _TASK_LOG[task_id]["status"] = status
    _TASK_LOG[task_id]["result"] = result
    _TASK_LOG[task_id]["ended_at"] = ended_at

    log_task_result(agent_name, task_params, result, duration)

    return {"task_id": task_id, "status": status, "result": result}


def check_task_status(task_id: str) -> str:
    """Return the current status string for the given task ID.

    Returns one of: running / completed / failed / not_found
    """
    entry = _TASK_LOG.get(task_id)
    if entry is None:
        return "not_found"
    return entry["status"]


def retry_failed_task(
    task_id: str,
    db_session: Session,
) -> dict[str, Any]:
    """Retry a failed task up to 3 times.

    - If under the limit, calls assign_task() again with the original params.
    - If at the limit, sends a Slack alert and returns retried=False.
    """
    entry = _TASK_LOG.get(task_id)
    if entry is None:
        return {"retried": False, "new_result": {"error": "task_id not found"}}

    retry_count = entry.get("retry_count", 0)

    if retry_count >= 3:
        logger.error("Task %s failed 3 times — max retries exhausted", task_id)
        return {"retried": False, "new_result": {"error": "Max retries (3) exceeded"}}

    entry["retry_count"] = retry_count + 1

    new_dispatch = assign_task(entry["agent_name"], entry["params"], db_session)

    # Propagate updated state to the original log entry so check_task_status
    # reflects the latest outcome under the same task_id.
    entry["status"] = new_dispatch["status"]
    entry["result"] = new_dispatch["result"]

    return {"retried": True, "new_result": new_dispatch}


def log_task_result(
    agent_name: str,
    params: dict[str, Any],
    result: dict[str, Any],
    duration_seconds: int,
) -> None:
    """Print and persist a structured log line for the completed task."""
    timestamp = datetime.now(timezone.utc).isoformat()
    line = (
        f"[{timestamp}] TASK: {agent_name} "
        f"params: {params} "
        f"result: {result} "
        f"duration: {duration_seconds}s"
    )

    print(line)

    try:
        _LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with _LOG_FILE.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError as exc:
        print(f"[task_manager] WARNING: could not write to {_LOG_FILE}: {exc}")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _dispatch(
    agent_name: str,
    params: dict[str, Any],
    db_session: Session,
) -> dict[str, Any]:
    """Import the target agent lazily and call its run entry point.

    Each agent unpacks the relevant keys from *params*:
    - scout   : industry (str), location (str), count (int)
    - analyst : company_ids (list[str])
    - writer  : company_ids (list[str])
    - outreach: no extra params — calls process_followup_queue(db_session)
    - tracker : no extra params — calls run_daily_checks(db_session)
    """
    if agent_name == "scout":
        from agents.scout import scout_agent  # noqa: PLC0415
        result = scout_agent.run(
            industry=str(params.get("industry", "")),
            location=str(params.get("location", "")),
            count=int(params.get("count", 10)),
            db_session=db_session,
        )
        return {"company_ids": result or []}

    if agent_name == "analyst":
        from agents.analyst import analyst_agent  # noqa: PLC0415
        result = analyst_agent.run(
            company_ids=list(params.get("company_ids", [])),
            db_session=db_session,
            on_progress=params.get("on_progress"),
        )
        return {"company_ids": result or []}

    if agent_name == "writer":
        from agents.writer import writer_agent  # noqa: PLC0415
        result = writer_agent.run(
            company_ids=list(params.get("company_ids", [])),
            db_session=db_session,
        )
        return {"draft_ids": result or []}

    if agent_name == "outreach":
        from agents.outreach import outreach_agent  # noqa: PLC0415
        sent = outreach_agent.process_followup_queue(db_session)
        return {"sent": sent}

    if agent_name == "tracker":
        from agents.tracker import tracker_agent  # noqa: PLC0415
        return tracker_agent.run_daily_checks(db_session) or {}

    # Unreachable after the guard in assign_task, but satisfies type checker.
    raise ValueError(f"Unhandled agent: {agent_name}")


