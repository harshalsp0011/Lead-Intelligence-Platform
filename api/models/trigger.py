from __future__ import annotations

"""Pydantic models for pipeline trigger API request and response payloads.

Purpose:
- Defines schemas for starting a pipeline run, and for polling its status.

Dependencies:
- `pydantic` v2 for model validation and serialization.

Usage:
- Import the class you need in a route handler:
      from api.models.trigger import TriggerRequest, TriggerResponse
"""

from datetime import datetime
import logging
from typing import Any, Dict, Optional
from uuid import UUID

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

_VALID_INDUSTRIES = {
    "healthcare",
    "hospitality",
    "manufacturing",
    "retail",
    "public_sector",
    "office",
}

_VALID_RUN_MODES = {"full", "scout_only", "analyst_only", "writer_only"}


class TriggerRequest(BaseModel):
    """Request body to start a new pipeline run."""

    industry: str = Field(
        ...,
        description=(
            "Target industry. One of: healthcare, hospitality, manufacturing, "
            "retail, public_sector, office."
        ),
    )
    location: str = Field(
        ...,
        description='City and state in "City, ST" format, e.g. "Buffalo, NY".',
    )
    count: int = Field(
        default=20,
        ge=5,
        le=100,
        description="Number of companies to scout (5–100).",
    )
    run_mode: str = Field(
        default="full",
        description=(
            "Pipeline execution mode. One of: full, scout_only, "
            "analyst_only, writer_only."
        ),
    )

    def model_post_init(self, __context: Any) -> None:  # noqa: ANN401
        if self.industry not in _VALID_INDUSTRIES:
            logger.error("Invalid trigger industry received: %s", self.industry)
            raise ValueError(
                f"industry must be one of {sorted(_VALID_INDUSTRIES)}, "
                f"got '{self.industry}'."
            )
        if self.run_mode not in _VALID_RUN_MODES:
            logger.error("Invalid trigger run_mode received: %s", self.run_mode)
            raise ValueError(
                f"run_mode must be one of {sorted(_VALID_RUN_MODES)}, "
                f"got '{self.run_mode}'."
            )


class TriggerResponse(BaseModel):
    """Immediate response after a pipeline run has been started."""

    trigger_id: UUID
    run_mode: str
    industry: str
    location: str
    count: int
    started_at: datetime
    status: str = Field(
        ...,
        description="One of: started, running, completed, failed.",
    )


class TriggerStatusResponse(BaseModel):
    """Detailed status of an in-progress or completed pipeline run."""

    trigger_id: UUID
    status: str
    run_mode: Optional[str] = None
    started_at: datetime
    completed_at: Optional[datetime] = None
    duration_seconds: Optional[int] = None
    result_summary: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    progress: list[Dict[str, Any]] = Field(default_factory=list)
    total: Optional[int] = None
