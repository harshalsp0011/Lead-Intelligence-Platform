from __future__ import annotations

"""Pipeline monitoring API routes.

Purpose:
- Read-only endpoints exposing live pipeline health and activity.
- GET /pipeline/status   — stage counts + pipeline value
- GET /pipeline/health   — per-service health check
- GET /pipeline/activity — recent outreach activity feed
- GET /pipeline/issues   — stuck-pipeline issue strings

Dependencies:
- `api.dependencies` for DB session and API key guard.
- `api.models.pipeline` for response schemas.
- `agents.orchestrator.pipeline_monitor` for all data retrieval.

Usage:
- Include this router in api/main.py with prefix='/pipeline'.
"""

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.dependencies import get_db, verify_api_key
from api.models.pipeline import (
    ActivityItem,
    AgentHealthResponse,
    PipelineStatusResponse,
    RecentActivityResponse,
)
from agents.orchestrator import pipeline_monitor
from database.orm_models import AgentRun, AgentRunLog

router = APIRouter(dependencies=[Depends(verify_api_key)])


def _fmt_currency(value: float) -> str:
    v = float(value or 0)
    if v >= 1_000_000:
        return f"${v / 1_000_000:.1f}M"
    if v >= 1_000:
        return f"${v / 1_000:.0f}k"
    return f"${v:.0f}"


@router.get("/status", response_model=PipelineStatusResponse)
def pipeline_status(db: Session = Depends(get_db)) -> PipelineStatusResponse:
    """Return current lead counts at every pipeline stage plus pipeline value."""
    counts = pipeline_monitor.get_pipeline_counts(db)
    value = pipeline_monitor.get_pipeline_value(db)

    active_statuses = {"new", "enriched", "scored", "approved", "contacted", "replied"}
    total_active = sum(
        counts.get(s, 0) for s in active_statuses
    )

    mid = float(value.get("total_savings_mid") or 0.0)

    return PipelineStatusResponse(
        new=counts.get("new", 0),
        enriched=counts.get("enriched", 0),
        scored=counts.get("scored", 0),
        approved=counts.get("approved", 0),
        contacted=counts.get("contacted", 0),
        replied=counts.get("replied", 0),
        meeting_booked=counts.get("meeting_booked", 0),
        won=counts.get("won", 0),
        lost=counts.get("lost", 0),
        no_response=counts.get("no_response", 0),
        archived=counts.get("archived", 0),
        total_active=total_active,
        pipeline_value_mid=mid,
        pipeline_value_formatted=_fmt_currency(mid),
        last_updated=datetime.now(timezone.utc),
    )


@router.get("/health", response_model=AgentHealthResponse)
def pipeline_health() -> AgentHealthResponse:
    """Return health status for all core services."""
    health: dict[str, Any] = pipeline_monitor.check_agent_health()
    return AgentHealthResponse(
        postgres=health.get("postgres", {"status": "error", "message": "unavailable"}),
        ollama=health.get("ollama",    {"status": "error", "message": "unavailable"}),
        api=health.get("api",          {"status": "error", "message": "unavailable"}),
        airflow=health.get("airflow",  {"status": "error", "message": "unavailable"}),
        sendgrid=health.get("sendgrid",{"status": "error", "message": "unavailable"}),
        tavily=health.get("tavily",    {"status": "error", "message": "unavailable"}),
        slack=health.get("slack",      {"status": "error", "message": "unavailable"}),
    )


@router.get("/activity", response_model=RecentActivityResponse)
def pipeline_activity(
    limit: int = Query(default=10, ge=1, le=100),
    db: Session = Depends(get_db),
) -> RecentActivityResponse:
    """Return the most recent outreach activity events."""
    raw: list[dict[str, Any]] = pipeline_monitor.get_recent_activity(db, limit=limit)

    items: list[ActivityItem] = []
    for row in raw:
        event_type = str(row.get("event_type") or "")
        company = str(row.get("company_name") or "unknown")
        description = f"{company} — {event_type.replace('_', ' ')}"

        items.append(
            ActivityItem(
                timestamp=row.get("timestamp") or datetime.now(timezone.utc),
                company_name=company,
                contact_name=row.get("contact_name"),
                event_type=event_type,
                description=description,
            )
        )

    return RecentActivityResponse(activities=items, total_count=len(items))


@router.get("/issues")
def pipeline_issues(db: Session = Depends(get_db)) -> list[str]:
    """Return human-readable strings describing stuck pipeline conditions."""
    return pipeline_monitor.detect_stuck_pipeline(db)


@router.get("/run/{run_id}")
def get_run_status(run_id: UUID, db: Session = Depends(get_db)) -> dict[str, Any]:
    """Return status and counters for a specific agent run by run_id."""
    run: AgentRun | None = db.get(AgentRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    logs = db.execute(
        select(AgentRunLog)
        .where(AgentRunLog.run_id == run_id)
        .order_by(AgentRunLog.created_at.asc())
    ).scalars().all()

    return {
        "run_id": str(run.id),
        "status": run.status,
        "current_stage": run.current_stage,
        "trigger_source": run.trigger_source,
        "companies_found": run.companies_found,
        "companies_scored": run.companies_scored,
        "companies_approved": run.companies_approved,
        "drafts_created": run.drafts_created,
        "emails_sent": run.emails_sent,
        "started_at": run.created_at.isoformat() if run.created_at else None,
        "updated_at": run.updated_at.isoformat() if run.updated_at else None,
        "error_message": run.error_message,
        "log_count": len(logs),
        "recent_logs": [
            {
                "agent": lg.agent,
                "action": lg.action,
                "status": lg.status,
                "output_summary": lg.output_summary,
                "created_at": lg.created_at.isoformat() if lg.created_at else None,
            }
            for lg in logs[-5:]  # last 5 log entries
        ],
    }
