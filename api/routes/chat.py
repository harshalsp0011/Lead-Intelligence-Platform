from __future__ import annotations

"""Chat API routes.

Purpose:
- POST /chat  — start a chat run in the background, return run_id immediately
- GET  /chat/result/{run_id} — poll for completion; returns status + final reply

The background approach lets the frontend:
  1. Get a run_id instantly
  2. Poll /pipeline/run/{run_id} every 2 s to see live progress steps
  3. Poll /chat/result/{run_id} every 2 s to detect when the agent finishes

Dependencies:
- agents.chat_agent.run_chat
- database.connection.SessionLocal for background-thread DB sessions
"""

import logging
import threading
import uuid as uuid_mod
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from agents.chat_agent import run_chat
from database.connection import SessionLocal

logger = logging.getLogger(__name__)

router = APIRouter()

# ---------------------------------------------------------------------------
# In-memory result store  (run_id → result dict)
# Cleared automatically when a result is fetched for the first time.
# ---------------------------------------------------------------------------
_results: dict[str, dict[str, Any]] = {}


class ChatStartResponse(BaseModel):
    run_id: str
    status: str


@router.post("", response_model=ChatStartResponse)
def chat(body: dict) -> ChatStartResponse:
    """Start a chat run in the background and return a run_id immediately.

    The client should then:
    - Poll GET /pipeline/run/{run_id} every 2 s for live progress logs
    - Poll GET /chat/result/{run_id}   every 2 s until status != 'pending'
    """
    message = str(body.get("message", "")).strip()
    if not message:
        raise HTTPException(status_code=422, detail="message is required")

    run_id = str(uuid_mod.uuid4())
    _results[run_id] = {"status": "pending", "run_id": run_id}

    logger.info("Chat request received — run_id=%s message=%r", run_id, message[:120])

    def _run_background() -> None:
        db = SessionLocal()
        try:
            result = run_chat(message, db, run_id=run_id)
            _results[run_id] = {
                "status": "done",
                "reply": result["reply"],
                "data": result["data"],
                "run_id": result["run_id"],
            }
            logger.info("Chat run %s completed", run_id)
        except Exception as exc:
            logger.exception("Background chat failed for run_id=%s", run_id)
            _results[run_id] = {
                "status": "error",
                "reply": f"Sorry, an error occurred: {exc}",
                "data": {},
                "run_id": run_id,
            }
        finally:
            db.close()

    thread = threading.Thread(target=_run_background, daemon=True)
    thread.start()

    return ChatStartResponse(run_id=run_id, status="started")


@router.get("/result/{run_id}")
def chat_result(run_id: str) -> dict[str, Any]:
    """Return the result of a chat run.

    Returns:
    - {"status": "pending", "run_id": "..."} while still running
    - {"status": "done",    "run_id": "...", "reply": "...", "data": {...}} when finished
    - {"status": "error",   "run_id": "...", "reply": "error details"} on failure
    """
    result = _results.get(run_id)
    if not result:
        raise HTTPException(status_code=404, detail="Run not found — may have expired")
    return result
