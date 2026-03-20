from __future__ import annotations

"""Human-in-loop approval API routes.

Purpose:
- POST /approvals/leads  — bulk approve/reject scored leads for a run
- GET  /approvals/leads  — list pending approval requests

When a run's leads are approved here:
- Selected company lead_scores.approved_human = True
- Rejected companies status = 'archived'
- agent_runs.status updated to 'analyst_complete'
- human_approval_requests row updated

Dependencies:
- `api.dependencies` for DB session and API key guard.
- `database.orm_models` for HumanApprovalRequest, AgentRun, LeadScore, Company.

Usage:
- Include this router in api/main.py with prefix='/approvals'.
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.dependencies import get_db, verify_api_key
from config.settings import get_settings
from database.orm_models import AgentRun, AgentRunLog, Company, HumanApprovalRequest, LeadScore

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=[Depends(verify_api_key)])


class LeadsApprovalRequest(BaseModel):
    run_id: str
    approved_company_ids: list[str]
    rejected_company_ids: list[str] = []
    approved_by: str = "user"
    rejection_reason: str = ""


class LeadsApprovalResponse(BaseModel):
    success: bool
    approved_count: int
    rejected_count: int
    run_status: str
    message: str


@router.post("/leads", response_model=LeadsApprovalResponse)
def approve_leads_for_run(
    body: LeadsApprovalRequest,
    db: Session = Depends(get_db),
) -> LeadsApprovalResponse:
    """Bulk approve/reject leads for a pipeline run.

    Approves selected companies and rejects the rest.
    Updates agent_runs.status to analyst_complete when done.
    """
    now = datetime.now(timezone.utc)
    run_id = uuid.UUID(body.run_id)

    # Approve selected companies
    approved_count = 0
    for cid_str in body.approved_company_ids:
        cid = uuid.UUID(cid_str)
        score_row = db.execute(
            select(LeadScore)
            .where(LeadScore.company_id == cid)
            .order_by(LeadScore.scored_at.desc())
            .limit(1)
        ).scalar_one_or_none()

        if score_row:
            score_row.approved_human = True
            score_row.approved_by = body.approved_by
            score_row.approved_at = now

        company = db.execute(
            select(Company).where(Company.id == cid)
        ).scalar_one_or_none()
        if company:
            company.status = "approved"
            company.updated_at = now

        approved_count += 1

    # Archive rejected companies
    rejected_count = 0
    for cid_str in body.rejected_company_ids:
        cid = uuid.UUID(cid_str)
        company = db.execute(
            select(Company).where(Company.id == cid)
        ).scalar_one_or_none()
        if company:
            company.status = "archived"
            company.updated_at = now
        rejected_count += 1

    # Update agent run status
    agent_run = db.get(AgentRun, run_id)
    if agent_run:
        agent_run.companies_approved = approved_count
        agent_run.status = "analyst_complete"
        agent_run.current_stage = "writer"
        db.add(AgentRunLog(
            id=uuid.uuid4(),
            run_id=run_id,
            agent="human",
            action="leads_approved",
            status="success",
            output_summary=(
                f"Approved {approved_count} leads, rejected {rejected_count}. "
                f"Approved by: {body.approved_by}"
            ),
            logged_at=now,
        ))

    # Update or close the approval request
    approval_req = db.execute(
        select(HumanApprovalRequest)
        .where(
            HumanApprovalRequest.run_id == run_id,
            HumanApprovalRequest.approval_type == "leads",
            HumanApprovalRequest.status == "pending",
        )
        .order_by(HumanApprovalRequest.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()

    if approval_req:
        approval_req.status = "approved"
        approval_req.approved_by = body.approved_by
        approval_req.approved_at = now

    db.commit()
    logger.info(
        "Leads approved for run %s — approved=%d rejected=%d by=%s",
        body.run_id, approved_count, rejected_count, body.approved_by,
    )

    return LeadsApprovalResponse(
        success=True,
        approved_count=approved_count,
        rejected_count=rejected_count,
        run_status="analyst_complete",
        message=f"Approved {approved_count} leads. Pipeline continues to Writer stage.",
    )


@router.get("/leads")
def list_pending_approvals(db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    """List all pending lead approval requests."""
    rows = db.execute(
        select(HumanApprovalRequest)
        .where(
            HumanApprovalRequest.approval_type == "leads",
            HumanApprovalRequest.status == "pending",
        )
        .order_by(HumanApprovalRequest.created_at.desc())
    ).scalars().all()

    return [
        {
            "id": str(r.id),
            "run_id": str(r.run_id) if r.run_id else None,
            "items_count": r.items_count,
            "items_summary": r.items_summary,
            "notification_sent": r.notification_sent,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "expires_at": r.expires_at.isoformat() if r.expires_at else None,
        }
        for r in rows
    ]
