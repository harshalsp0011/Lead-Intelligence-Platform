from __future__ import annotations

"""Pydantic models for pipeline status and health API response payloads.

Purpose:
- Defines schemas for pipeline stage counts, agent health checks, and
  recent outreach activity responses.

Dependencies:
- `pydantic` v2 for model validation and serialization.

Usage:
- Import the class you need in a route handler:
      from api.models.pipeline import PipelineStatusResponse, AgentHealthResponse
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, computed_field


class PipelineStatusResponse(BaseModel):
    """Lead counts at every pipeline stage plus live pipeline value."""

    new: int
    enriched: int
    scored: int
    approved: int
    contacted: int
    replied: int
    meeting_booked: int
    won: int
    lost: int
    no_response: int
    archived: int
    total_active: int
    pipeline_value_mid: float
    pipeline_value_formatted: str
    last_updated: datetime
    contacts_with: int = 0      # companies that have at least 1 contact saved
    contacts_needed: int = 0    # scored/approved companies still missing a contact
    pending_analyst: int = 0    # new/enriched companies waiting to be scored
    pending_writer: int = 0     # approved companies with no draft yet (true writer queue)


class AgentHealthResponse(BaseModel):
    """Health status dict per service and a computed overall status."""

    postgres: Dict[str, Any]
    ollama: Dict[str, Any]
    api: Dict[str, Any]
    airflow: Dict[str, Any]
    sendgrid: Dict[str, Any]
    tavily: Dict[str, Any]
    slack: Dict[str, Any]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def overall_status(self) -> str:
        """Return 'healthy', 'degraded', or 'warning' based on service statuses."""
        service_statuses = [
            str(self.postgres.get("status", "")),
            str(self.ollama.get("status", "")),
            str(self.api.get("status", "")),
            str(self.airflow.get("status", "")),
            str(self.sendgrid.get("status", "")),
            str(self.tavily.get("status", "")),
            str(self.slack.get("status", "")),
        ]
        if any(s == "error" for s in service_statuses):
            return "degraded"
        if any(s == "warning" for s in service_statuses):
            return "warning"
        return "healthy"


class ActivityItem(BaseModel):
    """Single outreach event for the activity feed."""

    timestamp: datetime
    company_name: str
    contact_name: Optional[str] = None
    event_type: str
    description: str


class RecentActivityResponse(BaseModel):
    """List of recent outreach activity items."""

    activities: List[ActivityItem]
    total_count: int
