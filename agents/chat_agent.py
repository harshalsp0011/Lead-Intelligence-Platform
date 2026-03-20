from __future__ import annotations

"""Conversational agent for the Utility Lead Intelligence Platform.

How the agent works:
- User sends a natural-language message.
- A system prompt gives the agent its personality and rules.
- LangChain builds a ReAct loop: LLM reads message + tool descriptions,
  picks the right tool, calls it, reads the result, writes a reply.
- Tools are Python functions with docstrings — the LLM reads those docstrings
  to decide which tool to call and what args to pass.
- Every run is tracked in agent_runs + agent_run_logs tables.

Agent framework: LangChain AgentExecutor + create_tool_calling_agent
LLM: ChatOllama (llama3.2 local) or ChatOpenAI (gpt-4o-mini) via LLM_PROVIDER env var

Usage:
    from agents.chat_agent import run_chat
    result = run_chat("find 10 healthcare companies in Buffalo NY", db)
    # result = {"reply": "...", "data": {...}, "run_id": "..."}
"""

import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any

from langchain.agents import create_agent
from langchain_core.messages import HumanMessage
from langchain_core.tools import tool
from sqlalchemy import select
from sqlalchemy.orm import Session

from config.settings import get_settings
from database.orm_models import (
    AgentRun,
    AgentRunLog,
    Company,
    LeadScore,
    OutreachEvent,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# LangSmith tracing — activate at module load so every agent call is traced
# ---------------------------------------------------------------------------

def _setup_tracing() -> None:
    """Enable LangSmith tracing if LANGCHAIN_API_KEY is set in the environment.

    LangChain reads LANGCHAIN_TRACING_V2 and LANGCHAIN_API_KEY automatically,
    but we set them explicitly here so Docker env vars are always applied before
    any LangChain import initialises its internal tracer.
    """
    settings = get_settings()
    if settings.LANGCHAIN_API_KEY:
        os.environ["LANGCHAIN_TRACING_V2"] = "true"
        os.environ["LANGCHAIN_API_KEY"] = settings.LANGCHAIN_API_KEY
        os.environ["LANGCHAIN_PROJECT"] = settings.LANGCHAIN_PROJECT
        logger.info("LangSmith tracing enabled — project: %s", settings.LANGCHAIN_PROJECT)
    else:
        logger.info("LangSmith tracing disabled (LANGCHAIN_API_KEY not set)")

_setup_tracing()


# ---------------------------------------------------------------------------
# System prompt — personality and rules given to the LLM
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are Scout, the Lead Intelligence Agent for Troy & Banks, \
a utility cost consulting firm based in Buffalo, NY.

Your job is to help the sales team find utility companies, track outreach, and report on pipeline activity.

== CRITICAL TOOL USAGE RULES ==

DO NOT call any tool for these types of messages — reply conversationally only:
- Greetings: "hi", "hello", "hey", "good morning"
- Capability questions: "what can you do", "how can you help", "what are your features"
- General questions: "tell me about yourself", "what is this", "how does this work"
- Confirmations: "ok", "got it", "thanks", "sounds good"

ONLY call a tool when the user gives an explicit data command:
- "find companies" → call search_companies
- "show leads", "show me leads", "get leads", "list leads" → call get_leads
- "who did we email", "outreach history" → call get_outreach_history
- "any replies", "who replied" → call get_replies
- "run the full pipeline", "run everything" → call run_full_pipeline
- "approve lead", "approve company", "approve these" → call approve_leads

When in doubt — do NOT call a tool. Ask the user to clarify what they need.

== RESPONSE RULES ==

- For greetings: say "Hi, I'm Scout, Lead Intelligence Agent for Troy & Banks. \
I can find companies, show scored leads, check outreach history, or run the full pipeline. What do you need?"
- For capability questions: list the 5 capabilities in plain text. No tool calls.
- Keep all replies short and direct.
- Never make up company names, scores, or contact data.
"""


# ---------------------------------------------------------------------------
# LLM factory
# ---------------------------------------------------------------------------

def _build_llm() -> Any:
    """Return a LangChain chat model based on LLM_PROVIDER setting."""
    settings = get_settings()
    if settings.LLM_PROVIDER == "openai":
        from pydantic import SecretStr
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=settings.LLM_MODEL,
            api_key=SecretStr(settings.OPENAI_API_KEY),
            temperature=0,
        )
    from langchain_ollama import ChatOllama
    return ChatOllama(
        model=settings.LLM_MODEL,
        base_url=settings.OLLAMA_BASE_URL,
        temperature=0,
    )


# ---------------------------------------------------------------------------
# Run record helpers
# ---------------------------------------------------------------------------

def _create_run(db: Session, trigger_input: dict[str, Any], run_id: uuid.UUID | None = None) -> AgentRun:
    """Insert a new agent_runs row and return it."""
    now = datetime.now(timezone.utc)
    run = AgentRun(
        id=run_id or uuid.uuid4(),
        trigger_source="chat",
        trigger_input=trigger_input,
        status="started",
        current_stage="chat",
        started_at=now,
        created_at=now,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def _log_action(
    db: Session,
    run_id: uuid.UUID,
    agent: str,
    action: str,
    status: str,
    output_summary: str = "",
    duration_ms: int | None = None,
    error_message: str | None = None,
) -> None:
    """Append one row to agent_run_logs."""
    entry = AgentRunLog(
        id=uuid.uuid4(),
        run_id=run_id,
        agent=agent,
        action=action,
        status=status,
        output_summary=output_summary,
        duration_ms=duration_ms,
        error_message=error_message,
        logged_at=datetime.now(timezone.utc),
    )
    db.add(entry)
    db.commit()


def _finish_run(db: Session, run: AgentRun, status: str = "completed") -> None:
    """Mark the run as finished."""
    run.status = status
    run.completed_at = datetime.now(timezone.utc)
    db.commit()


# ---------------------------------------------------------------------------
# Tools — the LLM reads each docstring to decide which one to call
# ---------------------------------------------------------------------------

def _make_tools(db: Session, results: dict[str, Any], run: AgentRun) -> list[Any]:
    """Create LangChain tools bound to the current DB session and run."""

    @tool
    def search_companies(industry: str, location: str, count: int = 10) -> str:
        """Find companies in a specific industry and location and store them in the database.
        Use this when the user asks to find, search, fetch, or discover companies.
        Args:
            industry: e.g. 'healthcare', 'hospitality', 'manufacturing', 'retail'
            location: e.g. 'Buffalo NY', 'New York', 'Chicago IL'
            count: how many companies to find (default 10)
        """
        import time
        from agents.scout import scout_agent

        start = time.time()
        run.current_stage = "scout"
        run.status = "scout_running"
        db.commit()

        _log_action(db, run.id, "scout", "progress", "info",
                    output_summary=f"Scout starting — finding {count} {industry} companies in {location}")

        try:
            company_ids = scout_agent.run(industry, location, count, db, run_id=str(run.id))
            duration = int((time.time() - start) * 1000)

            run.companies_found = len(company_ids)
            run.status = "scout_complete"
            db.commit()

            companies = db.execute(
                select(Company).where(Company.id.in_([uuid.UUID(cid) for cid in company_ids]))
            ).scalars().all()

            results["companies"] = [
                {
                    "company_id": str(c.id),
                    "name": c.name,
                    "industry": c.industry or "",
                    "city": c.city or "",
                    "state": c.state or "",
                    "website": c.website or "",
                    "source": c.source or "",
                    "status": c.status or "new",
                }
                for c in companies
            ]

            _log_action(
                db, run.id, "scout", "companies_found", "success",
                output_summary=f"Found {len(company_ids)} companies in {industry} / {location}",
                duration_ms=duration,
            )
            return json.dumps({"found": len(company_ids), "industry": industry, "location": location})

        except Exception as exc:
            _log_action(db, run.id, "scout", "companies_found", "failure", error_message=str(exc))
            run.status = "failed"
            run.error_message = str(exc)
            db.commit()
            return json.dumps({"error": str(exc)})

    @tool
    def get_leads(tier: str = "", industry: str = "") -> str:
        """Get scored leads from the database.
        Use when the user asks for leads, scored companies, high-tier leads, or pipeline results.
        Args:
            tier: filter by 'high', 'medium', or 'low' — leave blank for all
            industry: filter by industry name — leave blank for all
        """
        query = select(Company, LeadScore).join(
            LeadScore, LeadScore.company_id == Company.id, isouter=True
        )
        if industry:
            query = query.where(Company.industry == industry.lower())
        if tier:
            query = query.where(LeadScore.tier == tier.lower())

        rows = db.execute(query).all()

        leads = [
            {
                "company_id": str(company.id),
                "name": company.name,
                "industry": company.industry or "",
                "city": company.city or "",
                "state": company.state or "",
                "score": float(score.score or 0) if score else 0,
                "tier": score.tier or "unscored" if score else "unscored",
                "approved": bool(score.approved_human) if score else False,
                "status": company.status or "new",
            }
            for company, score in rows
        ]
        leads.sort(key=lambda x: x["score"], reverse=True)
        results["leads"] = leads[:50]

        _log_action(db, run.id, "chat", "get_leads", "success",
                    output_summary=f"Returned {len(leads)} leads (tier={tier or 'all'}, industry={industry or 'all'})")
        return json.dumps({"count": len(leads), "tier_filter": tier, "industry_filter": industry})

    @tool
    def get_outreach_history() -> str:
        """Get companies that have already been sent emails.
        Use when the user asks about companies already contacted, emailed, or in outreach.
        """
        rows = db.execute(
            select(Company, OutreachEvent)
            .join(OutreachEvent, OutreachEvent.company_id == Company.id)
            .where(OutreachEvent.event_type == "sent")
            .order_by(OutreachEvent.event_at.desc())
        ).all()

        history = [
            {
                "company_id": str(company.id),
                "name": company.name,
                "industry": company.industry or "",
                "city": company.city or "",
                "emailed_at": event.event_at.isoformat() if event.event_at else "",
                "follow_up_number": event.follow_up_number or 0,
                "status": company.status or "",
            }
            for company, event in rows
        ]
        results["outreach_history"] = history

        _log_action(db, run.id, "chat", "get_outreach_history", "success",
                    output_summary=f"Returned {len(history)} outreach records")
        return json.dumps({"count": len(history)})

    @tool
    def get_replies() -> str:
        """Get email replies received from prospects.
        Use when the user asks about replies, responses, interested prospects, or hot leads.
        """
        rows = db.execute(
            select(Company, OutreachEvent)
            .join(OutreachEvent, OutreachEvent.company_id == Company.id)
            .where(OutreachEvent.event_type == "replied")
            .order_by(OutreachEvent.event_at.desc())
        ).all()

        replies = [
            {
                "company_id": str(company.id),
                "name": company.name,
                "industry": company.industry or "",
                "reply_sentiment": event.reply_sentiment or "unknown",
                "reply_snippet": (event.reply_content or "")[:200],
                "replied_at": event.event_at.isoformat() if event.event_at else "",
            }
            for company, event in rows
        ]
        results["replies"] = replies

        _log_action(db, run.id, "chat", "get_replies", "success",
                    output_summary=f"Returned {len(replies)} replies")
        return json.dumps({"count": len(replies)})

    @tool
    def run_full_pipeline(industry: str, location: str, count: int = 10) -> str:
        """Run the complete pipeline: Scout → Analyst → Writer for a given industry and location.
        Only use this when the user explicitly asks to run the full pipeline, start everything,
        or do a complete end-to-end run.
        Args:
            industry: target industry e.g. 'healthcare'
            location: target location e.g. 'Buffalo NY'
            count: number of companies to target (default 10)
        """
        import time
        from agents.orchestrator import orchestrator

        start = time.time()
        run.current_stage = "orchestrator"
        run.status = "scout_running"
        db.commit()

        try:
            summary = orchestrator.run_full_pipeline(industry, location, count, db)
            duration = int((time.time() - start) * 1000)

            run.companies_found = summary.get("companies_found", 0)
            run.companies_scored = summary.get("scored_high", 0) + summary.get("scored_medium", 0)
            run.drafts_created = summary.get("drafts_created", 0)
            run.status = "writer_awaiting_approval"
            run.current_stage = "writer"
            db.commit()

            results["pipeline_summary"] = summary
            _log_action(
                db, run.id, "orchestrator", "full_pipeline_complete", "success",
                output_summary=str(summary),
                duration_ms=duration,
            )
            return json.dumps(summary)

        except Exception as exc:
            _log_action(db, run.id, "orchestrator", "full_pipeline_complete",
                        "failure", error_message=str(exc))
            run.status = "failed"
            run.error_message = str(exc)
            db.commit()
            return json.dumps({"error": str(exc)})

    @tool
    def approve_leads(company_ids: list[str], approved_by: str = "sales_team") -> str:
        """Approve specific leads by their company IDs so Writer can draft emails for them.
        Use when the user says 'approve lead', 'approve company', 'approve these leads',
        or provides a list of company IDs/names to approve.
        Args:
            company_ids: list of company UUID strings to approve
            approved_by: name of the approver (default 'sales_team')
        """
        from datetime import datetime, timezone as tz
        now = datetime.now(tz.utc)
        approved_count = 0

        for cid_str in company_ids:
            try:
                cid = uuid.UUID(cid_str)
                score_row = db.execute(
                    select(LeadScore)
                    .where(LeadScore.company_id == cid)
                    .order_by(LeadScore.scored_at.desc())
                    .limit(1)
                ).scalar_one_or_none()

                if score_row:
                    score_row.approved_human = True
                    score_row.approved_by = approved_by
                    score_row.approved_at = now

                company = db.execute(
                    select(Company).where(Company.id == cid)
                ).scalar_one_or_none()
                if company:
                    company.status = "approved"
                    company.updated_at = now

                approved_count += 1
            except Exception as exc:
                logger.warning("Failed to approve company %s: %s", cid_str, exc)

        db.commit()
        _log_action(db, run.id, "chat", "approve_leads", "success",
                    output_summary=f"Approved {approved_count} leads via chat")

        return json.dumps({"approved": approved_count, "approved_by": approved_by})

    return [search_companies, get_leads, get_outreach_history, get_replies, run_full_pipeline, approve_leads]


# ---------------------------------------------------------------------------
# Conversational message detector
# ---------------------------------------------------------------------------

_CONVERSATIONAL_PATTERNS = [
    "hi", "hello", "hey", "good morning", "good afternoon", "good evening",
    "what can you do", "what do you do", "how can you help", "what are you",
    "tell me about yourself", "how does this work", "what is this",
    "help", "thanks", "thank you", "ok", "okay", "got it", "sounds good",
    "great", "nice", "cool", "awesome",
]

def _is_conversational(message: str) -> bool:
    """Return True if the message is small talk or a capability question.
    These bypass the agent loop entirely — no tools will be called.
    """
    msg = message.lower().strip().rstrip("?!.")
    return any(msg == p or msg.startswith(p) for p in _CONVERSATIONAL_PATTERNS)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run_chat(message: str, db: Session, run_id: str | None = None) -> dict[str, Any]:
    """Process a natural-language message and return a reply with structured data.

    Args:
        message: User's natural-language input
        db: SQLAlchemy session
        run_id: Optional pre-generated UUID string — lets the caller reserve a run_id
                before spawning this in a background thread so the frontend can start
                polling progress logs immediately.

    Returns:
        {
            "reply":  str,    # agent's text response shown in chat bubble
            "data":   dict,   # structured results rendered as inline cards in UI
            "run_id": str,    # UUID of the agent_run row — for polling /pipeline/run/{id}
        }
    """
    results: dict[str, Any] = {
        "companies": [],
        "leads": [],
        "outreach_history": [],
        "replies": [],
        "pipeline_summary": None,
    }

    parsed_run_id = uuid.UUID(run_id) if run_id else None
    run = _create_run(db, {"message": message}, run_id=parsed_run_id)

    try:
        llm = _build_llm()

        if _is_conversational(message):
            # Bypass tools entirely — direct LLM reply.
            # Prevents llama3.2 from calling tools on greetings/capability questions
            # regardless of system prompt instructions.
            from langchain_core.messages import SystemMessage
            response = llm.invoke([
                SystemMessage(content=SYSTEM_PROMPT),
                HumanMessage(content=message),
            ])
            reply = response.content
        else:
            # Data request — run the full agent with tools
            tools = _make_tools(db, results, run)
            agent = create_agent(llm, tools, system_prompt=SYSTEM_PROMPT)
            response = agent.invoke({"messages": [HumanMessage(content=message)]})
            reply = response["messages"][-1].content

        _finish_run(db, run, "completed")
        logger.info("Chat run %s completed. message=%r", run.id, message[:80])

    except Exception as exc:
        logger.exception("Chat agent failed. run_id=%s", run.id)
        _finish_run(db, run, "failed")
        reply = (
            "Sorry, I ran into an error processing your request. "
            f"Details: {exc}"
        )

    return {
        "reply": reply,
        "data": results,
        "run_id": str(run.id),
    }
