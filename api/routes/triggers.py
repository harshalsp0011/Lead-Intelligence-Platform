from __future__ import annotations

"""Pipeline trigger API routes.

Purpose:
- Endpoints that kick off pipeline stages as FastAPI background tasks and
  expose a status-polling endpoint.
- POST /trigger/full      — full scout→analyst→enrich→write pipeline
- POST /trigger/scout     — scout only
- POST /trigger/analyst   — analyst only (queries unscored companies)
- POST /trigger/writer    — writer only (approved high-tier companies)
- POST /trigger/outreach  — outreach only
- GET  /trigger/{id}/status — poll trigger status

Dependencies:
- `api.dependencies` for DB session and API key guard.
- `api.models.trigger` for request/response schemas.
- `agents.orchestrator.orchestrator` for pipeline stage functions.
- `database.connection.SessionLocal` for background-task DB sessions.

Usage:
- Include this router in api/main.py with prefix='/trigger'.
"""

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.dependencies import get_db, verify_api_key
from api.models.trigger import TriggerRequest, TriggerResponse, TriggerStatusResponse
from database.connection import SessionLocal
from database.orm_models import Company

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=[Depends(verify_api_key)])

# In-process trigger registry  {trigger_id: status_dict}
_REGISTRY: dict[str, dict[str, Any]] = {}


# ---------------------------------------------------------------------------
# Background task helpers
# ---------------------------------------------------------------------------


def _wrap(trigger_id: str, fn: Any, *args: Any) -> None:
    """Run fn(*args) in background, updating the registry on completion."""
    db: Session = SessionLocal()
    try:
        result = fn(*args, db)
        _REGISTRY[trigger_id].update(
            status="completed",
            completed_at=datetime.now(timezone.utc),
            result_summary=result if isinstance(result, dict) else {"result": result},
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("Trigger %s failed: %s", trigger_id, exc)
        _REGISTRY[trigger_id].update(
            status="failed",
            completed_at=datetime.now(timezone.utc),
            error_message=str(exc),
        )
    finally:
        db.close()


def _register(run_mode: str, req_dict: dict[str, Any]) -> tuple[str, datetime]:
    """Create a registry entry and return (trigger_id, started_at)."""
    trigger_id = str(uuid4())
    started_at = datetime.now(timezone.utc)
    _REGISTRY[trigger_id] = {
        "run_mode": run_mode,
        "status": "running",
        "started_at": started_at,
        "completed_at": None,
        "result_summary": None,
        "error_message": None,
        **req_dict,
    }
    return trigger_id, started_at


def _trigger_response(
    trigger_id: str,
    started_at: datetime,
    run_mode: str,
    industry: str = "",
    location: str = "",
    count: int = 0,
) -> TriggerResponse:
    return TriggerResponse(
        trigger_id=UUID(trigger_id),
        run_mode=run_mode,
        industry=industry,
        location=location,
        count=count,
        started_at=started_at,
        status="started",
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post("/full", response_model=TriggerResponse)
def trigger_full(
    body: TriggerRequest,
    background_tasks: BackgroundTasks,
) -> TriggerResponse:
    """Start the full pipeline (scout → analyst → enrich → write) in background."""
    from agents.orchestrator import orchestrator  # noqa: PLC0415

    trigger_id, started_at = _register(
        "full",
        {"industry": body.industry, "location": body.location, "count": body.count},
    )

    def _run(db: Session) -> dict[str, Any]:
        return orchestrator.run_full_pipeline(
            body.industry, body.location, body.count, db
        )

    background_tasks.add_task(_wrap, trigger_id, _run)

    return _trigger_response(
        trigger_id, started_at, "full",
        body.industry, body.location, body.count,
    )


@router.post("/scout", response_model=TriggerResponse)
def trigger_scout(
    body: TriggerRequest,
    background_tasks: BackgroundTasks,
) -> TriggerResponse:
    """Run the scout stage in background."""
    from agents.orchestrator import orchestrator  # noqa: PLC0415

    trigger_id, started_at = _register(
        "scout_only",
        {"industry": body.industry, "location": body.location, "count": body.count},
    )

    def _run(db: Session) -> dict[str, Any]:
        return orchestrator.run_scout(body.industry, body.location, body.count, db)

    background_tasks.add_task(_wrap, trigger_id, _run)

    return _trigger_response(
        trigger_id, started_at, "scout_only",
        body.industry, body.location, body.count,
    )


@router.post("/analyst", response_model=TriggerResponse)
def trigger_analyst(
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> TriggerResponse:
    """Run the analyst stage for all unscored companies in background."""
    from agents.orchestrator import orchestrator  # noqa: PLC0415

    # Gather company IDs that need scoring.
    company_ids: list[str] = [
        str(cid) for cid in db.execute(
            select(Company.id)
            .where(Company.status.in_(["new", "enriched"]))
            .order_by(Company.created_at.asc())
        ).scalars().all()
    ]

    trigger_id, started_at = _register(
        "analyst_only", {"company_ids_count": len(company_ids)}
    )

    def _run(session: Session) -> dict[str, Any]:
        return orchestrator.run_analyst(company_ids, session)

    background_tasks.add_task(_wrap, trigger_id, _run)

    return _trigger_response(trigger_id, started_at, "analyst_only")


@router.post("/writer", response_model=TriggerResponse)
def trigger_writer(background_tasks: BackgroundTasks) -> TriggerResponse:
    """Run the writer stage (approved high-tier companies) in background."""
    from agents.orchestrator import orchestrator  # noqa: PLC0415

    trigger_id, started_at = _register("writer_only", {})

    def _run(db: Session) -> dict[str, Any]:
        return orchestrator.run_writer(db)

    background_tasks.add_task(_wrap, trigger_id, _run)

    return _trigger_response(trigger_id, started_at, "writer_only")


@router.post("/outreach", response_model=TriggerResponse)
def trigger_outreach(background_tasks: BackgroundTasks) -> TriggerResponse:
    """Run the outreach stage (send approved drafts + follow-ups) in background."""
    from agents.orchestrator import orchestrator  # noqa: PLC0415

    trigger_id, started_at = _register("outreach", {})

    def _run(db: Session) -> dict[str, Any]:
        return orchestrator.run_outreach(db)

    background_tasks.add_task(_wrap, trigger_id, _run)

    return _trigger_response(trigger_id, started_at, "outreach")


@router.get("/{trigger_id}/status", response_model=TriggerStatusResponse)
def trigger_status(trigger_id: UUID) -> TriggerStatusResponse:
    """Poll the current status of a trigger by its ID."""
    entry = _REGISTRY.get(str(trigger_id))
    if not entry:
        return TriggerStatusResponse(
            trigger_id=trigger_id,
            status="not_found",
            started_at=datetime.now(timezone.utc),
        )

    completed_at: datetime | None = entry.get("completed_at")
    duration: int | None = None
    if completed_at and entry.get("started_at"):
        duration = int((completed_at - entry["started_at"]).total_seconds())

    return TriggerStatusResponse(
        trigger_id=trigger_id,
        status=str(entry.get("status") or "unknown"),
        started_at=entry["started_at"],
        completed_at=completed_at,
        duration_seconds=duration,
        result_summary=entry.get("result_summary"),
        error_message=entry.get("error_message"),
    )
