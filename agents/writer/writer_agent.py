from __future__ import annotations

"""Writer Agent — Phase C: Context-Aware Generation + Critic Loop.

How it works:
1. Load company data (name, industry, city, state, site_count, savings estimates,
   score_reason) + contact (name, title, email) from DB.
2. Writer LLM reasons about the company context and writes a personalised email.
   It reads score_reason (written by Analyst) to understand WHY this company is
   a good fit — no template filling.
3. Critic evaluates the draft on a 0–10 rubric (5 criteria × 2 pts each).
4. If score < 7: Writer rewrites using Critic's specific feedback. Max 2 rewrites.
5. If score still < 7 after 2 rewrites: save with low_confidence = true.
6. Save draft with critic_score, low_confidence, rewrite_count fields.

No-contact fallback:
  Old behaviour: skip company if no contact found.
  New behaviour: write a generic draft addressed to "[Company] team".
                 Draft is saved with contact_id = NULL.
                 Human fills in TO before approving.

Agentic concepts:
  Context-Aware Generation  — LLM reads score_reason + company signals, reasons
                              about the best angle before writing.
  Self-Critique / Reflection — Critic evaluates output, Writer rewrites on feedback.
  Uncertainty Flagging       — low_confidence=true when agent can't reach threshold.
  Graceful Degradation       — no contact → generic draft, not a skip.
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from agents.analyst import enrichment_client
from agents.writer import critic_agent, llm_connector, template_engine
from config.settings import get_settings
from database.orm_models import AgentRun, Company, CompanyFeature, EmailDraft, EmailWinRate, LeadScore

logger = logging.getLogger(__name__)

_MAX_REWRITES = 2
_PASS_THRESHOLD = 7.0

# Minimum emails sent before win rate data is trusted
_WIN_RATE_MIN_SENT = 5

# Valid angle identifiers the LLM can choose from
_VALID_ANGLES = {
    "cost_savings",
    "audit_offer",
    "risk_reduction",
    "multi_site_savings",
    "deregulation_opportunity",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_uuid(value: str, label: str = "id") -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except (ValueError, AttributeError) as exc:
        raise ValueError(f"Invalid {label}: {value!r}") from exc


def _read(record: Any, key: str) -> Any:
    if record is None:
        return None
    return record.get(key) if isinstance(record, dict) else getattr(record, key, None)


def _str(v: Any) -> str:
    return str(v).strip() if v is not None else ""


def _float(v: Any) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _int(v: Any) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


def get_best_angle(industry: str, db_session: Session) -> str | None:
    """Query email_win_rate for the best-performing angle for this industry.

    Returns the template_id with the highest reply_rate, or None if not enough
    data exists yet (cold start — let the LLM pick freely).

    Agentic concept: Learning from feedback — Writer reads historical win rates
    to bias its angle selection toward what has worked in this industry.
    """
    row = db_session.execute(
        select(EmailWinRate)
        .where(
            EmailWinRate.industry == industry,
            EmailWinRate.emails_sent >= _WIN_RATE_MIN_SENT,
        )
        .order_by(EmailWinRate.reply_rate.desc())
        .limit(1)
    ).scalar()

    if row is None:
        return None

    logger.info(
        "[writer] Win rate hint for industry=%s: angle=%s reply_rate=%.1f%% (sent=%d)",
        industry, row.template_id, row.reply_rate * 100, row.emails_sent,
    )
    return str(row.template_id)


def format_savings(amount: float) -> str:
    if amount >= 1_000_000:
        return f"${amount / 1_000_000:.1f}M"
    if amount >= 1_000:
        return f"${amount / 1_000:.0f}k"
    return f"${amount:.0f}"


# ---------------------------------------------------------------------------
# LLM writer calls
# ---------------------------------------------------------------------------

def _call_llm(prompt: str) -> str:
    provider = llm_connector.select_provider()
    if provider == "openai":
        return llm_connector.call_openai(prompt)
    return llm_connector.call_ollama(prompt)


_WRITER_PROMPT = """You are writing a cold outreach email on behalf of a utility cost consulting firm.
Your goal: get a 15-minute intro call or a free energy audit scheduled.

== COMPANY PROFILE ==
Company:   {company_name}
Industry:  {industry}
Location:  {city}, {state}
Sites:     {site_count} location(s)
Est. annual utility savings: {savings_mid} (range: {savings_low} – {savings_high})
Deregulated state: {deregulated}
Analyst note (why this company is a good fit):
  {score_reason}

== CONTACT ==
Name:  {contact_name}
Title: {contact_title}

{angle_hint}== AVAILABLE ANGLES ==
Choose one angle that best fits this company:
- cost_savings         : lead with the dollar savings estimate
- audit_offer          : lead with a free no-commitment energy audit
- risk_reduction       : lead with utility cost volatility / budget risk
- multi_site_savings   : lead with multi-location efficiency opportunity
- deregulation_opportunity : lead with open energy market / supplier switch

== YOUR TASK ==
First, reason (2–3 sentences) about what angle will work best for this specific company.
Consider: their industry, number of sites, savings potential, the analyst note, and their state.
Pick the angle name from the list above.

Then write the email. Requirements:
- Subject line: specific to this company (include name or a detail), not generic
- Opening: reference something specific about them (expansion, industry, location)
- Body: mention the savings estimate (use the mid figure)
- CTA: one clear ask — free audit, 15-min call, or reply to schedule
- Sign-off: professional, from the consulting firm
- Length: 100–160 words for the body (not too long, not too short)
- Tone: warm, direct, human — not template-like or salesy

Return in this exact format:
REASONING: <your 2–3 sentence reasoning>
ANGLE: <one angle name from the list above>
SUBJECT: <subject line>
BODY:
<full email body>"""


_REWRITE_PROMPT = """You wrote an outreach email that was reviewed and needs improvement.

== ORIGINAL EMAIL ==
Subject: {subject}

{body}

== CRITIC FEEDBACK ==
Score: {score}/10
Issue: {feedback}

== TASK ==
Rewrite the email to fix the issue above. Keep everything that was good.
Same format — return:
SUBJECT: <subject line>
BODY:
<full email body>"""


def _write_draft(context: dict[str, Any]) -> tuple[str, str, str]:
    """Call Writer LLM. Returns (subject, body, angle)."""
    prompt = _WRITER_PROMPT.format(**context)
    raw = _call_llm(prompt)
    return _parse_writer_output(raw)


def _rewrite_draft(subject: str, body: str, score: float, feedback: str, angle: str) -> tuple[str, str, str]:
    """Ask Writer to rewrite given Critic feedback. Returns (subject, body, angle).

    Angle is preserved from the original draft — rewrites fix tone/content,
    not the overall approach.
    """
    prompt = _REWRITE_PROMPT.format(
        subject=subject,
        body=body,
        score=score,
        feedback=feedback,
    )
    raw = _call_llm(prompt)
    new_subject, new_body, new_angle = _parse_writer_output(raw)
    # Keep original angle through rewrites; only adopt if LLM explicitly changed it
    return new_subject, new_body, new_angle if new_angle in _VALID_ANGLES else angle


_HEADER_PREFIXES = ("SUBJECT:", "ANGLE:", "BODY:", "REASONING:", "== ")

# Phrases the LLM appends after the email body explaining its own output
_EXPLANATION_STARTERS = (
    "i made the following",
    "i've made the following",
    "here are the changes",
    "here's what i changed",
    "these changes aim",
    "note:",
    "changes made:",
    "key changes:",
    "i changed",
    "i've updated",
    "modifications:",
)


def _strip_llm_explanation(body: str) -> str:
    """Remove any post-email self-explanation the LLM appended after the body."""
    lines = body.splitlines()
    cutoff = len(lines)
    for i, line in enumerate(lines):
        low = line.strip().lower()
        if any(low.startswith(p) for p in _EXPLANATION_STARTERS):
            cutoff = i
            break
    return "\n".join(lines[:cutoff]).strip()


def _parse_writer_output(raw: str) -> tuple[str, str, str]:
    """Parse SUBJECT / BODY / ANGLE from Writer LLM output.

    Handles two formats llama3.2 emits:
      Format A: explicit BODY: marker on its own line
      Format B: body starts immediately after SUBJECT: with no BODY: marker

    Returns (subject, body, angle). angle falls back to 'cost_savings' if missing.
    """
    subject = ""
    angle = ""
    body_lines: list[str] = []
    in_body = False
    subject_found = False

    for line in raw.splitlines():
        stripped = line.strip()
        upper = stripped.upper()

        if upper.startswith("SUBJECT:"):
            subject = stripped[len("SUBJECT:"):].strip()
            in_body = False
            subject_found = True
        elif upper.startswith("ANGLE:"):
            angle = stripped[len("ANGLE:"):].strip().lower()
            in_body = False
        elif upper.startswith("BODY:"):
            in_body = True
            after = stripped[len("BODY:"):].strip()
            if after:
                body_lines.append(after)
        elif upper.startswith("REASONING:"):
            in_body = False
        elif in_body:
            body_lines.append(line)
        elif subject_found:
            # Format B: no BODY: marker — collect non-header lines after SUBJECT:
            is_header = any(upper.startswith(p) for p in _HEADER_PREFIXES)
            if not is_header and (stripped or body_lines):
                body_lines.append(line)

    body = _strip_llm_explanation("\n".join(body_lines).strip())

    # Fallbacks if parsing failed
    if not subject:
        subject = "Utility cost savings opportunity"
    if not body:
        body = raw.strip()
    if angle not in _VALID_ANGLES:
        angle = "cost_savings"

    return subject, body, angle


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------

def run(
    company_ids: list[str],
    db_session: Session,
    run_id: str | None = None,
    on_progress: Any | None = None,
) -> list[str]:
    """Generate drafts for approved companies. Returns created draft IDs.

    run_id: optional AgentRun UUID string — if provided, increments
    agent_runs.drafts_created after each successful draft so the Pipeline
    page can show live progress.

    on_progress(entry): optional callback emitted at each step per company.
    entry keys: idx, name, step, critic_score, rewrites, done, low_confidence
    """
    # Load AgentRun row for live counter updates (may be None)
    agent_run: AgentRun | None = None
    if run_id:
        try:
            import uuid as _uuid  # noqa: PLC0415
            agent_run = db_session.get(AgentRun, _uuid.UUID(run_id))
        except Exception:
            logger.warning("[writer] Could not load AgentRun run_id=%s — run tracking disabled", run_id)

    created: list[str] = []
    for idx, company_id in enumerate(company_ids, start=1):
        # Build per-company emit closure capturing idx + company name
        company_name = company_id  # fallback until loaded
        try:
            _c = db_session.get(Company, _parse_uuid(company_id))
            if _c:
                company_name = str(_c.name or company_id)
        except Exception:
            pass

        def _emit(step: str, **kw: Any) -> None:
            if on_progress:
                on_progress({"idx": idx, "name": company_name, "step": step, **kw})

        try:
            draft_id = process_one_company(
                company_id=company_id,
                db_session=db_session,
                on_progress=_emit,
            )
            if draft_id:
                created.append(draft_id)
                # Increment live counter on AgentRun
                if agent_run is not None:
                    agent_run.drafts_created = len(created)
                    db_session.flush()
        except Exception:
            db_session.rollback()
            logger.exception("Writer failed for company_id=%s", company_id)
            _emit("❌ Failed", done=True, critic_score=None, rewrites=0, low_confidence=False)

    return created


def process_one_company(
    company_id: str,
    db_session: Session,
    on_progress: Any | None = None,
) -> str | None:
    """Generate one email draft for an approved company.

    Runs Writer → Critic → optional rewrite loop → saves draft.
    Returns draft UUID string, or None if company/score data is missing.

    on_progress(step, **kw): optional step callback. Called at:
      "✍️ Writing"       — Writer LLM call started
      "🔍 Critic"         — Critic evaluation started
      "↩️ Rewrite N/M"    — Rewrite N started
      "✅ Done"            — Draft saved successfully
      "⚠️ Low confidence" — Draft saved but never passed critic threshold
    """
    def _emit(step: str, **kw: Any) -> None:
        if on_progress:
            on_progress(step, **kw)
    cid = _parse_uuid(company_id, "company_id")

    # --- Load company, features, score ---
    company = db_session.get(Company, cid)
    features = db_session.execute(
        select(CompanyFeature)
        .where(CompanyFeature.company_id == cid)
        .order_by(CompanyFeature.computed_at.desc())
        .limit(1)
    ).scalar()
    score = db_session.execute(
        select(LeadScore)
        .where(LeadScore.company_id == cid)
        .order_by(LeadScore.scored_at.desc())
        .limit(1)
    ).scalar()

    if not company or not score:
        logger.warning("Missing company/score for company_id=%s — skipping", company_id)
        return None

    # --- Load contact (graceful fallback if none found) ---
    contact = enrichment_client.get_priority_contact(company_id=company_id, db_session=db_session)
    contact_id: str | None = None
    contact_name = "there"
    contact_title = ""
    contact_email = ""

    if contact:
        contact_id = str(_read(contact, "id") or "")
        full_name = _str(_read(contact, "full_name"))
        contact_name = full_name.split()[0] if full_name else "there"
        contact_title = _str(_read(contact, "title"))
        contact_email = _str(_read(contact, "email"))
    else:
        logger.info(
            "No contact for company_id=%s — writing generic draft (no-contact fallback)",
            company_id,
        )
        contact_name = "there"   # "Hi there" generic opener

    # --- Build writer context ---
    settings = get_settings()
    savings_low = _float(_read(features, "savings_low")) if features else 0.0
    savings_mid = _float(_read(features, "savings_mid")) if features else 0.0
    savings_high = _float(_read(features, "savings_high")) if features else 0.0
    site_count = _int(_read(features, "estimated_site_count")) if features else (
        _int(_read(company, "site_count")) or 1
    )
    deregulated = bool(_read(features, "deregulated_state")) if features else False

    # --- Win rate hint (3C learning layer) ---
    industry = _str(_read(company, "industry"))
    best_angle = get_best_angle(industry, db_session)
    if best_angle:
        angle_hint = (
            f"== WIN RATE HINT ==\n"
            f"For {industry}, the angle '{best_angle}' has the highest reply rate "
            f"based on past emails. Prefer this angle unless the company signals strongly suggest otherwise.\n\n"
        )
    else:
        angle_hint = ""  # cold start — let LLM pick freely

    writer_context = {
        "company_name":   _str(_read(company, "name")),
        "industry":       industry,
        "city":           _str(_read(company, "city")),
        "state":          _str(_read(company, "state")),
        "site_count":     site_count,
        "savings_low":    format_savings(savings_low),
        "savings_mid":    format_savings(savings_mid),
        "savings_high":   format_savings(savings_high),
        "deregulated":    "yes" if deregulated else "no",
        "score_reason":   _str(_read(score, "score_reason")) or "Strong utility spend signals.",
        "contact_name":   contact_name,
        "contact_title":  contact_title,
        "angle_hint":     angle_hint,
    }

    # Critic context (same data, formatted for critic prompt)
    critic_context = {
        "company_name":  writer_context["company_name"],
        "industry":      writer_context["industry"],
        "city":          writer_context["city"],
        "state":         writer_context["state"],
        "site_count":    str(site_count),
        "savings_mid":   writer_context["savings_mid"],
        "score_reason":  writer_context["score_reason"],
        "contact_name":  contact_name,
        "contact_title": contact_title,
    }

    # --- Writer + Critic loop ---
    _emit("✍️ Writing", done=False, critic_score=None, rewrites=0, low_confidence=False)
    subject, body, angle = _write_draft(writer_context)
    rewrite_count = 0

    _emit("🔍 Critic", done=False, critic_score=None, rewrites=0, low_confidence=False)
    critic_result = critic_agent.evaluate(subject, body, critic_context)
    critic_score = critic_result["score"]

    logger.info(
        "[writer] Initial draft for %s — angle=%s critic_score=%.1f passed=%s",
        writer_context["company_name"], angle, critic_score, critic_result["passed"],
    )

    while not critic_result["passed"] and rewrite_count < _MAX_REWRITES:
        rewrite_count += 1
        logger.info(
            "[writer] Rewrite %d/%d for %s — feedback: %s",
            rewrite_count, _MAX_REWRITES,
            writer_context["company_name"], critic_result["feedback"][:80],
        )
        _emit(
            f"↩️ Rewrite {rewrite_count}/{_MAX_REWRITES}",
            done=False, critic_score=critic_score, rewrites=rewrite_count, low_confidence=False,
        )
        subject, body, angle = _rewrite_draft(
            subject=subject,
            body=body,
            score=critic_score,
            feedback=critic_result["feedback"],
            angle=angle,
        )
        _emit("🔍 Critic", done=False, critic_score=None, rewrites=rewrite_count, low_confidence=False)
        critic_result = critic_agent.evaluate(subject, body, critic_context)
        critic_score = critic_result["score"]

    low_confidence = not critic_result["passed"]  # True if never passed after all rewrites
    if low_confidence:
        logger.warning(
            "[writer] Draft for %s saved with low_confidence=True (final score=%.1f)",
            writer_context["company_name"], critic_score,
        )

    # --- Save draft ---
    # template_used = angle chosen by the LLM (e.g. "cost_savings", "audit_offer")
    # This feeds email_win_rate when Tracker records an open/reply event.
    savings_range = f"{format_savings(savings_low)} – {format_savings(savings_high)}"
    draft_id = _save_draft(
        company_id=company_id,
        contact_id=contact_id,
        subject=subject,
        body=body,
        savings_estimate=savings_range,
        template_used=angle,
        critic_score=critic_score,
        low_confidence=low_confidence,
        rewrite_count=rewrite_count,
        db_session=db_session,
    )

    # Update company status
    if company is not None:
        company.status = "draft_created"
        company.updated_at = datetime.now(timezone.utc)
    db_session.commit()

    _emit(
        "⚠️ Low confidence" if low_confidence else "✅ Done",
        done=True, critic_score=critic_score, rewrites=rewrite_count, low_confidence=low_confidence,
    )
    logger.info(
        "[writer] Draft saved for %s — id=%s critic=%.1f rewrites=%d low_conf=%s",
        writer_context["company_name"], draft_id, critic_score, rewrite_count, low_confidence,
    )
    return draft_id


def _save_draft(
    company_id: str,
    contact_id: str | None,
    subject: str,
    body: str,
    savings_estimate: str,
    template_used: str,
    critic_score: float,
    low_confidence: bool,
    rewrite_count: int,
    db_session: Session,
) -> str:
    draft_id = uuid.uuid4()
    draft = EmailDraft(
        id=draft_id,
        company_id=_parse_uuid(company_id, "company_id"),
        contact_id=_parse_uuid(contact_id, "contact_id") if contact_id else None,
        subject_line=subject,
        body=body,
        savings_estimate=savings_estimate,
        template_used=template_used,
        critic_score=critic_score,
        low_confidence=low_confidence,
        rewrite_count=rewrite_count,
        approved_human=False,
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(draft)
    db_session.flush()
    return str(draft.id)


# keep backward-compat aliases used by older callers
def save_draft(
    company_id: str,
    contact_id: str,
    subject: str,
    body: str,
    template_used: str,
    savings_estimate: str,
    db_session: Session,
) -> str:
    return _save_draft(
        company_id=company_id,
        contact_id=contact_id,
        subject=subject,
        body=body,
        savings_estimate=savings_estimate,
        template_used=template_used,
        critic_score=0.0,
        low_confidence=False,
        rewrite_count=0,
        db_session=db_session,
    )


def build_context(company: Any, features: Any, score: Any, contact: Any, settings: Any) -> dict[str, Any]:
    """Legacy context builder — kept for any callers that use template_engine directly."""
    full_name = _str(_read(contact, "full_name"))
    first_name = full_name.split()[0] if full_name else "there"
    savings_low = _float(_read(features, "savings_low"))
    savings_mid = _float(_read(features, "savings_mid"))
    savings_high = _float(_read(features, "savings_high"))
    return {
        "contact_first_name":      first_name,
        "company_name":            _str(_read(company, "name")),
        "site_count":              _int(_read(features, "estimated_site_count")),
        "state":                   _str(_read(company, "state")),
        "industry":                _str(_read(company, "industry")),
        "savings_low_formatted":   format_savings(savings_low),
        "savings_high_formatted":  format_savings(savings_high),
        "savings_mid_formatted":   format_savings(savings_mid),
        "tb_sender_name":          _str(getattr(settings, "TB_SENDER_NAME", "")),
        "tb_sender_title":         _str(getattr(settings, "TB_SENDER_TITLE", "")),
        "tb_phone":                _str(getattr(settings, "TB_PHONE", "")),
        "unsubscribe_link":        "Reply STOP to unsubscribe",
    }


def format_savings_for_display(amount: float) -> str:
    return format_savings(amount)
