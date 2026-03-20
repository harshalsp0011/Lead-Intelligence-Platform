from __future__ import annotations

"""FastAPI application entry point for the Utility Lead Intelligence Platform.

Purpose:
- Assembles the FastAPI app, registers all route modules, applies CORS
  middleware, exposes a /health check, and wires the DB startup probe.

Dependencies:
- All api/routes/* modules.
- `database.connection.check_connection` for startup DB probe.
- `fastapi`, `uvicorn` for serving.

Usage:
- Development: `python api/main.py`
- Production: `uvicorn api.main:app --host 0.0.0.0 --port 8001`
"""

import logging
from datetime import datetime, timezone

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes import approvals, chat, emails, leads, pipeline, reports, triggers
from database import connection

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Utility Lead Intelligence Platform API",
    version="1.0.0",
    description="Agentic lead generation system for Troy & Banks",
)

# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------

app.include_router(chat.router,      prefix="/chat")
app.include_router(leads.router,     prefix="/leads")
app.include_router(emails.router,    prefix="/emails")
app.include_router(pipeline.router,  prefix="/pipeline")
app.include_router(triggers.router,  prefix="/trigger")
app.include_router(reports.router,   prefix="/reports")
app.include_router(approvals.router, prefix="/approvals")

# ---------------------------------------------------------------------------
# Health check  (unauthenticated — for load balancers and uptime monitors)
# ---------------------------------------------------------------------------

@app.get("/health", tags=["meta"])
def health_check() -> dict:
    return {
        "status": "ok",
        "service": "Utility Lead Intelligence Platform",
        "version": "1.0.0",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# Startup event
# ---------------------------------------------------------------------------

@app.on_event("startup")
def on_startup() -> None:
    if connection.check_connection():
        logger.info("API started successfully — database reachable.")
    else:
        logger.critical(
            "API started but database is NOT reachable. "
            "Check DATABASE_URL and PostgreSQL."
        )


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    uvicorn.run("api.main:app", host="0.0.0.0", port=8001, reload=True)
