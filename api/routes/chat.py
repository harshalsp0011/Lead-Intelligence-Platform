from __future__ import annotations

"""Chat API route.

Purpose:
- Accepts a natural-language message from the user and passes it to the
  conversational chat agent which decides what to do and returns results.

Endpoints:
- POST /chat  — send a message, get a reply + structured data back

Dependencies:
- agents.chat_agent.run_chat
- api.dependencies for DB session
"""

import logging
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from agents.chat_agent import run_chat
from api.dependencies import get_db

logger = logging.getLogger(__name__)

router = APIRouter()


class ChatRequest(BaseModel):
    message: str


class ChatResponse(BaseModel):
    reply: str
    data: dict[str, Any]
    run_id: str


@router.post("", response_model=ChatResponse)
def chat(body: ChatRequest, db: Session = Depends(get_db)) -> ChatResponse:
    """Send a natural-language message to the agent and get a response.

    Examples:
    - "find 10 healthcare companies in Buffalo NY"
    - "show me all high-tier leads"
    - "which companies have we already emailed?"
    - "did anyone reply to our emails?"
    - "run the full pipeline for manufacturing in Buffalo"
    """
    logger.info("Chat request received. message=%r", body.message[:120])
    result = run_chat(body.message, db)
    return ChatResponse(
        reply=result["reply"],
        data=result["data"],
        run_id=result["run_id"],
    )
