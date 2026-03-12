from __future__ import annotations

"""Main Writer Agent entry point for draft generation."""

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from agents.analyst import enrichment_client
from agents.writer import llm_connector, template_engine, tone_validator
from config.settings import get_settings
from database.orm_models import Company, CompanyFeature, EmailDraft, LeadScore


def _parse_uuid(value: str, label: str = "id") -> uuid.UUID:
    """Parse a UUID string; raises ValueError with a clear message on failure."""
    try:
        return uuid.UUID(str(value))
    except (ValueError, AttributeError) as exc:
        raise ValueError(f"Invalid {label}: {value!r}") from exc

logger = logging.getLogger(__name__)


def run(company_ids: list[str], db_session: Session) -> list[str]:
    """Generate drafts for approved companies and return created draft IDs."""
    created_draft_ids: list[str] = []

    for company_id in company_ids:
        lead_score: LeadScore | None = db_session.execute(
            select(LeadScore)
            .where(LeadScore.company_id == _parse_uuid(company_id, "company_id"))
            .order_by(LeadScore.scored_at.desc())
            .limit(1)
        ).scalar()

        if not lead_score or not bool(lead_score.approved_human):
            continue

        try:
            draft_id = process_one_company(company_id=company_id, db_session=db_session)
            if draft_id:
                created_draft_ids.append(draft_id)
        except Exception:
            db_session.rollback()
            logger.exception("Writer processing failed for company_id=%s", company_id)

    return created_draft_ids


def process_one_company(company_id: str, db_session: Session) -> str | None:
    """Build and store one email draft for a single approved company."""
    # Step 1: load company, features, score from DB.
    cid = _parse_uuid(company_id, "company_id")
    company: Company | None = db_session.get(Company, cid)

    features: CompanyFeature | None = db_session.execute(
        select(CompanyFeature)
        .where(CompanyFeature.company_id == cid)
        .order_by(CompanyFeature.computed_at.desc())
        .limit(1)
    ).scalar()

    score: LeadScore | None = db_session.execute(
        select(LeadScore)
        .where(LeadScore.company_id == cid)
        .order_by(LeadScore.scored_at.desc())
        .limit(1)
    ).scalar()

    if not company or not features or not score:
        logger.warning("Missing company/features/score for company_id=%s", company_id)
        return None

    # Step 2: get best contact.
    contact = enrichment_client.get_priority_contact(company_id=company_id, db_session=db_session)
    if not contact:
        logger.warning("No contact found for company_id=%s. Skipping draft generation.", company_id)
        return None

    settings = get_settings()

    # Step 3: call build_context from template_engine.
    base_context = template_engine.build_context(company, features, score, contact, settings)
    context = build_context(company, features, score, contact, settings)
    context = {**base_context, **context}

    industry = str(context.get("industry") or "healthcare")

    # Step 4: load template by industry.
    raw_template = template_engine.load_template(industry)

    # Step 5: fill static placeholders.
    filled_template = template_engine.fill_static_fields(raw_template, context)

    # Step 6: generate subject options and pick first.
    subject_candidates = _generate_subject_lines(context=context, draft_body=filled_template)
    default_subject = subject_candidates[0] if subject_candidates else str(context.get("subject_line") or "Utility savings opportunity")

    # Step 7: generate final body.
    generated_body = _generate_email_body(
        context=context,
        subject=default_subject,
        base_draft=filled_template,
    )

    # Step 8: validate tone and retry once if needed.
    validation = tone_validator.validate_tone(default_subject, generated_body)
    warning_flag = False

    if not bool(validation.get("passed")):
        logger.warning(
            "Tone validation failed for company_id=%s with issues=%s",
            company_id,
            validation.get("issues", []),
        )
        regenerated_body = _generate_email_body(
            context=context,
            subject=default_subject,
            base_draft=filled_template,
            retry_with_issues=validation.get("issues", []),
        )
        validation_retry = tone_validator.validate_tone(default_subject, regenerated_body)

        if bool(validation_retry.get("passed")):
            generated_body = regenerated_body
            validation = validation_retry
        else:
            generated_body = regenerated_body
            validation = validation_retry
            warning_flag = True

    # Step 9: save draft.
    savings_estimate = f"{context.get('savings_low_formatted', '')} - {context.get('savings_high_formatted', '')}"
    template_used = industry if not warning_flag else f"{industry}:tone_warning"

    draft_id = save_draft(
        company_id=company_id,
        contact_id=str(contact.get("id")),
        subject=default_subject,
        body=generated_body,
        template_used=template_used,
        savings_estimate=savings_estimate,
        db_session=db_session,
    )

    # Step 10: update company status.
    if company is not None:
        company.status = "draft_created"
        company.updated_at = datetime.now(timezone.utc)
    db_session.commit()

    return draft_id


def save_draft(
    company_id: str,
    contact_id: str,
    subject: str,
    body: str,
    template_used: str,
    savings_estimate: str,
    db_session: Session,
) -> str:
    """Insert one draft row with approved_human defaulting to false."""
    draft_id = uuid.uuid4()
    draft = EmailDraft(
        id=draft_id,
        company_id=_parse_uuid(company_id, "company_id"),
        contact_id=_parse_uuid(contact_id, "contact_id"),
        subject_line=subject,
        body=body,
        savings_estimate=savings_estimate,
        template_used=template_used,
        approved_human=False,
    )
    db_session.add(draft)
    db_session.flush()
    return str(draft.id)


def build_context(
    company: Any,
    features: Any,
    score: Any,
    contact: Any,
    settings: Any,
) -> dict[str, Any]:
    """Build complete template context dictionary for writer placeholders."""
    full_name = _read_field(contact, "full_name")
    first_name = (str(full_name).strip().split()[0] if full_name else "there")

    savings_low = _as_float(_read_field(features, "savings_low"))
    savings_mid = _as_float(_read_field(features, "savings_mid"))
    savings_high = _as_float(_read_field(features, "savings_high"))

    return {
        "contact_first_name": first_name,
        "company_name": _as_string(_read_field(company, "name")),
        "site_count": _as_int(_read_field(features, "estimated_site_count")),
        "state": _as_string(_read_field(company, "state")),
        "industry": _as_string(_read_field(company, "industry")),
        "savings_low_formatted": format_savings_for_display(savings_low),
        "savings_high_formatted": format_savings_for_display(savings_high),
        "savings_mid_formatted": format_savings_for_display(savings_mid),
        "tb_sender_name": _as_string(getattr(settings, "TB_SENDER_NAME", "")),
        "tb_sender_title": _as_string(getattr(settings, "TB_SENDER_TITLE", "")),
        "tb_phone": _as_string(getattr(settings, "TB_PHONE", "")),
        "unsubscribe_link": "Reply STOP to unsubscribe",
    }


def format_savings_for_display(amount: float) -> str:
    """Format a dollar value in compact outreach style."""
    value = float(amount)
    if value >= 1_000_000:
        return f"${value / 1_000_000:.1f}M"
    if value >= 1_000:
        return f"${value / 1_000:.0f}k"
    return f"${value:.0f}"


def _generate_subject_lines(context: dict[str, Any], draft_body: str) -> list[str]:
    generator = getattr(llm_connector, "generate_subject_lines", None)
    if callable(generator):
        try:
            subjects = generator(context=context, draft_body=draft_body)
            if isinstance(subjects, list):
                cleaned = [str(item).strip() for item in subjects if str(item).strip()]
                if cleaned:
                    return cleaned
        except Exception:
            logger.exception("llm_connector.generate_subject_lines failed; using fallback prompt")

    prompt = (
        "Generate 3 professional, concise outreach email subject lines. "
        "Return one per line without numbering.\n"
        f"Company: {context.get('company_name', '')}\n"
        f"Industry: {context.get('industry', '')}\n"
        f"Draft context:\n{draft_body}"
    )
    text_output = _call_provider(prompt)
    lines = [line.strip(" -\t") for line in text_output.splitlines() if line.strip()]
    return lines[:3] if lines else []


def _generate_email_body(
    context: dict[str, Any],
    subject: str,
    base_draft: str,
    retry_with_issues: list[str] | None = None,
) -> str:
    generator = getattr(llm_connector, "generate_email_body", None)
    if callable(generator):
        try:
            return str(
                generator(
                    context=context,
                    subject=subject,
                    base_draft=base_draft,
                    retry_with_issues=retry_with_issues,
                )
            )
        except Exception:
            logger.exception("llm_connector.generate_email_body failed; using fallback prompt")

    issues_text = ""
    if retry_with_issues:
        issues_text = "\nAddress these validation issues: " + "; ".join(str(item) for item in retry_with_issues)

    prompt = (
        "Rewrite this outreach email to be professional, specific, and concise. "
        "Preserve key facts and CTA, avoid hype.\n"
        f"Subject: {subject}\n"
        f"Company: {context.get('company_name', '')}\n"
        f"Industry: {context.get('industry', '')}\n"
        f"Base email:\n{base_draft}{issues_text}"
    )
    return _call_provider(prompt)


def _call_provider(prompt: str) -> str:
    provider = llm_connector.select_provider()
    if provider == "openai":
        return llm_connector.call_openai(prompt)
    return llm_connector.call_ollama(prompt)


def _read_field(record: Any, key: str) -> Any:
    if record is None:
        return None
    if isinstance(record, dict):
        return record.get(key)
    return getattr(record, key, None)


def _as_string(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _as_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _as_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
