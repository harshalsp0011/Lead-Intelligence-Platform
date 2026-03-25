from __future__ import annotations

"""Pydantic models for lead-related API request and response payloads.

Purpose:
- Defines strongly-typed schemas for lead listing, filtering, approval,
  and rejection endpoints.

Dependencies:
- `pydantic` v2 for model validation and serialization.

Usage:
- Import the class you need in a route handler:
      from api.models.lead import LeadResponse, LeadApproveRequest
"""

from datetime import date, datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class LeadResponse(BaseModel):
    """Full lead record returned by the API."""

    company_id: UUID
    company_name: str
    industry: str
    state: str
    city: Optional[str] = None
    phone: Optional[str] = None
    website: Optional[str] = None
    linkedin_search_url: Optional[str] = None
    site_count: int
    employee_count: int
    estimated_total_spend: float
    estimated_annual_utility_spend: float = 0.0
    estimated_annual_telecom_spend: float = 0.0
    savings_low: float
    savings_mid: float
    savings_high: float
    savings_low_formatted: str
    savings_mid_formatted: str
    savings_high_formatted: str
    tb_revenue_estimate: float
    score: float
    tier: str
    score_reason: str
    industry_fit_score: float = 0.0
    data_quality_score: float = 0.0
    multi_site_confirmed: bool = False
    approved_human: bool
    approved_by: Optional[str] = None
    approved_at: Optional[datetime] = None
    status: str
    contact_found: bool
    date_scored: datetime

    model_config = {"from_attributes": True}


class LeadApproveRequest(BaseModel):
    """Request body for approving a lead."""

    approved_by: str = Field(
        ..., description="Name of the sales manager approving the lead."
    )


class LeadRejectRequest(BaseModel):
    """Request body for rejecting a lead."""

    rejected_by: str
    rejection_reason: Optional[str] = None


class LeadListResponse(BaseModel):
    """Paginated list of leads with tier counts."""

    leads: List[LeadResponse]
    total_count: int
    high_count: int
    medium_count: int
    low_count: int
    pending_analysis_count: int = 0  # companies with status='new' — not yet scored
    page: int
    page_size: int


class LeadFilterParams(BaseModel):
    """Optional filters and pagination for the lead list endpoint."""

    industry: Optional[str] = None
    state: Optional[str] = None
    tier: Optional[str] = None
    status: Optional[str] = None
    min_score: Optional[float] = None
    max_score: Optional[float] = None
    date_from: Optional[date] = None
    date_to: Optional[date] = None
    search: Optional[str] = None
    page: int = 1
    page_size: int = 25
