from __future__ import annotations

"""Email draft management API routes.

Purpose:
- Endpoints for viewing, approving, editing, rejecting, and regenerating
  email drafts before outreach.
- GET  /emails               — paginated draft list
- GET  /emails/pending       — drafts awaiting approval (oldest first)
- GET  /emails/{id}          — single draft details
- PATCH /emails/{id}/approve
- PATCH /emails/{id}/edit
- PATCH /emails/{id}/reject
- POST  /emails/{id}/regenerate — regenerate draft via writer agent

Dependencies:
- `api.dependencies` for DB session and API key guard.
- `api.models.email` for request/response schemas.
- `agents.writer.writer_agent` for draft regeneration.
- `database.orm_models` for ORM-backed reads and writes.

Usage:
- Include this router in api/main.py with prefix='/emails'.
"""

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from api.dependencies import get_db, verify_api_key
from api.models.email import (
    EmailApproveRequest,
    EmailDraftResponse,
    EmailEditRequest,
    EmailListResponse,
    EmailRejectRequest,
)
from database.orm_models import Company, Contact, EmailDraft, OutreachEvent

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=[Depends(verify_api_key)])

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SENT_EVENT_TYPES = ("sent", "followup_sent")


def _draft_to_response(
    draft: EmailDraft,
    company: Company | None,
    contact: Contact | None,
) -> EmailDraftResponse:
    """Convert ORM models into the email draft API response schema."""
    return EmailDraftResponse(
        id=draft.id,
        company_id=draft.company_id,
        company_name=str(company.name if company else ""),
        contact_id=draft.contact_id,
        contact_name=str(contact.full_name if contact and contact.full_name else ""),
        contact_title=str(contact.title if contact and contact.title else ""),
        contact_email=str(contact.email if contact and contact.email else ""),
        subject_line=str(draft.subject_line or ""),
        body=str(draft.body or ""),
        savings_estimate=str(draft.savings_estimate or ""),
        template_used=str(draft.template_used or ""),
        created_at=draft.created_at or datetime.now(timezone.utc),
        approved_human=bool(draft.approved_human),
        approved_by=draft.approved_by,
        approved_at=draft.approved_at,
        edited_human=bool(draft.edited_human),
        critic_score=draft.critic_score,
        low_confidence=draft.low_confidence,
        rewrite_count=draft.rewrite_count,
    )


def _count_drafts(db: Session) -> dict[str, int]:
    """Return summary counters for the draft queue."""
    total_count = db.scalar(select(func.count()).select_from(EmailDraft)) or 0
    pending_approval = db.scalar(
        select(func.count())
        .select_from(EmailDraft)
        .where(or_(EmailDraft.approved_human.is_(False), EmailDraft.approved_human.is_(None)))
    ) or 0
    approved_count = db.scalar(
        select(func.count())
        .select_from(EmailDraft)
        .where(EmailDraft.approved_human.is_(True))
    ) or 0
    sent_count = db.scalar(
        select(func.count())
        .select_from(OutreachEvent)
        .where(OutreachEvent.event_type.in_(_SENT_EVENT_TYPES))
    ) or 0
    return {
        "total_count": int(total_count),
        "pending_approval": int(pending_approval),
        "approved_count": int(approved_count),
        "sent_count": int(sent_count),
    }


def _draft_query(*filters: Any) -> Any:
    """Build the shared ORM query used by list and detail endpoints."""
    statement = (
        select(EmailDraft, Company, Contact)
        .outerjoin(Company, Company.id == EmailDraft.company_id)
        .outerjoin(Contact, Contact.id == EmailDraft.contact_id)
    )
    if filters:
        statement = statement.where(*filters)
    return statement


# ---------------------------------------------------------------------------
# Routes  (literal paths before parameterised ones)
# ---------------------------------------------------------------------------

@router.get("/pending", response_model=EmailListResponse)
def list_pending_drafts(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
    db: Session = Depends(get_db),
) -> EmailListResponse:
    """Return drafts awaiting approval, oldest first."""
    offset = (page - 1) * page_size
    rows = db.execute(
        _draft_query(or_(EmailDraft.approved_human.is_(False), EmailDraft.approved_human.is_(None)))
        .order_by(EmailDraft.created_at.asc())
        .limit(page_size)
        .offset(offset)
    ).all()

    counts = _count_drafts(db)
    return EmailListResponse(
        drafts=[_draft_to_response(draft, company, contact) for draft, company, contact in rows],
        **counts,
    )


@router.get("", response_model=EmailListResponse)
def list_drafts(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
    approved_only: bool = Query(default=False),
    db: Session = Depends(get_db),
) -> EmailListResponse:
    """Return all email drafts with optional approved_only filter."""
    offset = (page - 1) * page_size
    filters: list[Any] = []
    if approved_only:
        filters.append(EmailDraft.approved_human.is_(True))

    rows = db.execute(
        _draft_query(*filters)
        .order_by(EmailDraft.created_at.desc())
        .limit(page_size)
        .offset(offset)
    ).all()

    counts = _count_drafts(db)
    return EmailListResponse(
        drafts=[_draft_to_response(draft, company, contact) for draft, company, contact in rows],
        **counts,
    )


@router.get("/{draft_id}", response_model=EmailDraftResponse)
def get_draft(draft_id: UUID, db: Session = Depends(get_db)) -> EmailDraftResponse:
    """Return a single email draft by ID."""
    row = db.execute(_draft_query(EmailDraft.id == draft_id)).first()

    if not row:
        logger.warning("Draft %s was requested but not found", draft_id)
        raise HTTPException(status_code=404, detail=f"Draft {draft_id} not found.")

    draft, company, contact = row
    return _draft_to_response(draft, company, contact)


@router.patch("/{draft_id}/approve")
def approve_draft(
    draft_id: UUID,
    body: EmailApproveRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Approve a draft and send the email immediately via the configured provider.

    Agentic concept: Human-in-the-Loop gate — human reviews and approves the
    AI-written draft before any email is sent. Approval triggers the actual send.

    Flow:
    1. Mark draft approved_human=True
    2. Call email_sender.send_email → sends via SendGrid/Instantly, logs outreach_event
    3. On success: set company.status = "contacted"
    4. Return {success, sent, message_id, message}
    """
    from agents.outreach.email_sender import send_email  # noqa: PLC0415

    draft = db.get(EmailDraft, draft_id)
    if draft is None:
        logger.warning("Draft %s could not be approved because it does not exist", draft_id)
        raise HTTPException(status_code=404, detail=f"Draft {draft_id} not found.")

    draft.approved_human = True
    draft.approved_by = body.approved_by
    draft.approved_at = datetime.now(timezone.utc)
    db.flush()  # persist approval before send attempt

    # --- Send the email ---
    send_result = send_email(draft_id=str(draft_id), db_session=db)
    sent = bool(send_result.get("success"))
    message_id = str(send_result.get("message_id") or "")

    if sent:
        # Update company status to "contacted"
        company = db.get(Company, draft.company_id)
        if company is not None:
            company.status = "contacted"
            company.updated_at = datetime.now(timezone.utc)
        logger.info(
            "Draft %s approved and sent by %s — message_id=%s",
            draft_id, body.approved_by, message_id,
        )
    else:
        logger.warning(
            "Draft %s approved by %s but send failed: %s",
            draft_id, body.approved_by, message_id,
        )

    db.commit()
    return {
        "success": True,
        "sent": sent,
        "message_id": message_id,
        "message": (
            f"Draft {draft_id} approved and sent." if sent
            else f"Draft {draft_id} approved but not sent: {message_id}"
        ),
    }


@router.patch("/{draft_id}/edit")
def edit_draft(
    draft_id: UUID,
    body: EmailEditRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Apply human edits to subject line and/or body of a draft."""
    draft = db.get(EmailDraft, draft_id)
    if draft is None:
        logger.warning("Draft %s could not be edited because it does not exist", draft_id)
        raise HTTPException(status_code=404, detail=f"Draft {draft_id} not found.")

    draft.edited_human = True
    if body.new_subject_line is not None:
        draft.subject_line = body.new_subject_line

    if body.new_body is not None:
        draft.body = body.new_body

    db.commit()
    logger.info("Draft %s edited by %s", draft_id, body.edited_by)
    return {"success": True, "message": f"Draft {draft_id} updated by {body.edited_by}."}


@router.patch("/{draft_id}/reject")
def reject_draft(
    draft_id: UUID,
    body: EmailRejectRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Delete a draft and reset the company back to 'approved' so it re-appears
    in the Writer queue and the Generate Drafts button count on the Triggers page."""
    draft = db.get(EmailDraft, draft_id)
    if draft is None:
        logger.warning("Draft %s could not be rejected because it does not exist", draft_id)
        raise HTTPException(status_code=404, detail=f"Draft {draft_id} not found.")

    company_id = draft.company_id
    db.delete(draft)

    # Reset company status so it re-appears in the pending Writer count
    company = db.get(Company, company_id) if company_id else None
    if company is not None and company.status == "draft_created":
        company.status = "approved"
        company.updated_at = datetime.now(timezone.utc)

    db.commit()

    logger.info(
        "Draft %s rejected by %s (reason=%s) — company %s reset to 'approved'",
        draft_id, body.rejected_by, body.rejection_reason, company_id,
    )
    return {
        "success": True,
        "message": (
            f"Draft {draft_id} rejected by {body.rejected_by}. "
            f"Reason: {body.rejection_reason or 'not provided'}."
        ),
    }


@router.post("/{draft_id}/regenerate", response_model=EmailDraftResponse)
def regenerate_draft(
    draft_id: UUID,
    db: Session = Depends(get_db),
) -> EmailDraftResponse:
    """Delete the current draft and generate a fresh one via the writer agent."""
    from agents.writer import writer_agent  # noqa: PLC0415

    existing = db.get(EmailDraft, draft_id)
    if existing is None:
        logger.warning("Draft %s could not be regenerated because it does not exist", draft_id)
        raise HTTPException(status_code=404, detail=f"Draft {draft_id} not found.")

    company_id = str(existing.company_id)

    db.delete(existing)
    # Briefly reset status so the company is re-eligible if regeneration fails
    company = db.get(Company, existing.company_id) if existing.company_id else None
    if company is not None and company.status == "draft_created":
        company.status = "approved"
    db.commit()

    new_draft_id = writer_agent.process_one_company(company_id=company_id, db_session=db)
    if not new_draft_id:
        logger.error("Writer agent failed to regenerate a draft for company %s", company_id)
        raise HTTPException(
            status_code=500,
            detail="Writer agent could not generate a new draft for this company.",
        )

    row = db.execute(_draft_query(EmailDraft.id == new_draft_id)).first()
    if not row:
        logger.error("Regenerated draft %s could not be reloaded after writer completion", new_draft_id)
        raise HTTPException(status_code=500, detail="Regenerated draft could not be retrieved.")

    draft, company, contact = row
    return _draft_to_response(draft, company, contact)
