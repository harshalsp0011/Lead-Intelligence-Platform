from __future__ import annotations

"""Pydantic models for email draft API request and response payloads.

Purpose:
- Defines strongly-typed schemas for draft listing, approval, editing,
  and rejection endpoints.

Dependencies:
- `pydantic` v2 for model validation and serialization.

Usage:
- Import the class you need in a route handler:
      from api.models.email import EmailDraftResponse, EmailApproveRequest
"""

from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel


class EmailDraftResponse(BaseModel):
    """Full email draft record returned by the API."""

    id: UUID
    company_id: UUID
    company_name: str
    contact_id: Optional[UUID] = None
    contact_name: str
    contact_title: str
    contact_email: str
    subject_line: str
    body: str
    savings_estimate: str
    template_used: str
    created_at: datetime
    approved_human: bool
    approved_by: Optional[str] = None
    approved_at: Optional[datetime] = None
    edited_human: bool
    # Phase C: Writer + Critic loop fields
    critic_score: Optional[float] = None
    low_confidence: Optional[bool] = None
    rewrite_count: Optional[int] = None

    model_config = {"from_attributes": True}


class EmailApproveRequest(BaseModel):
    """Request body for approving an email draft."""

    approved_by: str


class EmailEditRequest(BaseModel):
    """Request body for human-edited changes to a draft."""

    edited_by: str
    new_subject_line: Optional[str] = None
    new_body: Optional[str] = None


class EmailRejectRequest(BaseModel):
    """Request body for rejecting an email draft."""

    rejected_by: str
    rejection_reason: Optional[str] = None


class EmailListResponse(BaseModel):
    """List of email drafts with status-level counts."""

    drafts: List[EmailDraftResponse]
    total_count: int
    pending_approval: int
    approved_count: int
    sent_count: int
