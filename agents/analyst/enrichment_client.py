from __future__ import annotations

"""Contact enrichment client for Analyst workflow.

This module finds decision-maker contacts using the provider configured in
settings (`hunter` or `apollo`) and saves deduplicated contacts to the
`contacts` table.
"""

from typing import Any

import requests
from sqlalchemy import text
from sqlalchemy.orm import Session

from config.settings import get_settings

_TARGET_TITLES = {
    "cfo",
    "chief financial officer",
    "vp finance",
    "director of finance",
    "director of facilities",
    "facilities manager",
    "vp operations",
    "energy manager",
    "procurement manager",
    "controller",
}

_TITLE_PRIORITY = {
    "cfo": 1,
    "chief financial officer": 1,
    "vp finance": 2,
    "director of finance": 2,
    "director of facilities": 3,
    "facilities manager": 3,
    "vp operations": 4,
    "energy manager": 4,
}


def find_contacts(company_name: str, website_domain: str, db_session: Session) -> list[dict[str, Any]]:
    """Find and persist contacts for one company using the configured provider."""
    settings = get_settings()
    provider = (settings.ENRICHMENT_PROVIDER or "hunter").strip().lower()

    if provider == "hunter":
        raw_contacts = find_via_hunter(website_domain)
    elif provider == "apollo":
        raw_contacts = find_via_apollo(company_name, website_domain)
    else:
        raise ValueError(f"Unsupported ENRICHMENT_PROVIDER: {provider}")

    company_id = _resolve_company_id(company_name=company_name, website_domain=website_domain, db_session=db_session)
    if company_id is None:
        return []

    saved_contacts: list[dict[str, Any]] = []
    for contact in raw_contacts:
        contact_id = save_contact(contact_dict=contact, company_id=company_id, db_session=db_session)
        saved_contacts.append(
            {
                "id": contact_id,
                "company_id": company_id,
                "full_name": _clean_string(contact.get("full_name")),
                "title": _clean_string(contact.get("title")),
                "email": _clean_string(contact.get("email")),
                "linkedin_url": _clean_string(contact.get("linkedin_url")),
                "source": provider,
                "verified": bool(contact.get("verified") or False),
            }
        )

    return saved_contacts


def find_via_hunter(domain: str) -> list[dict[str, Any]]:
    """Call Hunter domain-search API and return filtered decision-maker contacts."""
    settings = get_settings()
    if not settings.HUNTER_API_KEY:
        return []

    response = requests.get(
        "https://api.hunter.io/v2/domain-search",
        params={"domain": domain, "api_key": settings.HUNTER_API_KEY},
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json()

    emails = payload.get("data", {}).get("emails", [])
    contacts: list[dict[str, Any]] = []

    for person in emails:
        title = _clean_string(person.get("position") or person.get("title"))
        if not _is_target_title(title):
            continue

        first_name = _clean_string(person.get("first_name"))
        last_name = _clean_string(person.get("last_name"))
        full_name = _clean_string(" ".join(part for part in [first_name, last_name] if part))
        email = _clean_string(person.get("value") or person.get("email"))

        if not email:
            continue

        contacts.append(
            {
                "full_name": full_name,
                "title": title,
                "email": email,
                "linkedin_url": _clean_string(person.get("linkedin") or person.get("linkedin_url")),
                "verified": bool(person.get("verification") == "verified" or person.get("confidence", 0) >= 85),
            }
        )

    return contacts


def find_via_apollo(company_name: str, domain: str) -> list[dict[str, Any]]:
    """Call Apollo people search API and return filtered decision-maker contacts."""
    settings = get_settings()
    if not settings.APOLLO_API_KEY:
        return []

    response = requests.post(
        "https://api.apollo.io/api/v1/mixed_people/search",
        headers={"x-api-key": settings.APOLLO_API_KEY, "Content-Type": "application/json"},
        json={
            "q_organization_domains": [domain],
            "person_seniorities": ["senior", "executive"],
            "person_titles": sorted(_TARGET_TITLES),
            "q_organization_name": company_name,
            "page": 1,
            "per_page": 25,
        },
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json()

    raw_people = payload.get("people") or payload.get("contacts") or []
    contacts: list[dict[str, Any]] = []

    for person in raw_people:
        title = _clean_string(person.get("title"))
        if not _is_target_title(title):
            continue

        email = _clean_string(person.get("email"))
        if not email:
            continue

        first_name = _clean_string(person.get("first_name"))
        last_name = _clean_string(person.get("last_name"))
        fallback_name = _clean_string(person.get("name"))
        full_name = _clean_string(" ".join(part for part in [first_name, last_name] if part)) or fallback_name

        contacts.append(
            {
                "full_name": full_name,
                "title": title,
                "email": email,
                "linkedin_url": _clean_string(person.get("linkedin_url")),
                "verified": bool(person.get("email_status") in {"verified", "deliverable"}),
            }
        )

    return contacts


def save_contact(contact_dict: dict[str, Any], company_id: str, db_session: Session) -> str:
    """Insert a contact row if email is new; otherwise return the existing contact ID."""
    email = _clean_string(contact_dict.get("email"))
    if not email:
        raise ValueError("Contact email is required to save contact")

    existing = db_session.execute(
        text(
            """
            SELECT id
            FROM contacts
            WHERE LOWER(email) = LOWER(:email)
            LIMIT 1
            """
        ),
        {"email": email},
    ).scalar_one_or_none()

    if existing is not None:
        return str(existing)

    provider = (get_settings().ENRICHMENT_PROVIDER or "hunter").strip().lower()

    inserted = db_session.execute(
        text(
            """
            INSERT INTO contacts (
                company_id,
                full_name,
                title,
                email,
                linkedin_url,
                source,
                verified,
                unsubscribed
            )
            VALUES (
                :company_id,
                :full_name,
                :title,
                :email,
                :linkedin_url,
                :source,
                :verified,
                false
            )
            RETURNING id
            """
        ),
        {
            "company_id": company_id,
            "full_name": _clean_string(contact_dict.get("full_name")),
            "title": _clean_string(contact_dict.get("title")),
            "email": email,
            "linkedin_url": _clean_string(contact_dict.get("linkedin_url")),
            "source": provider,
            "verified": bool(contact_dict.get("verified") or False),
        },
    ).scalar_one()

    db_session.commit()
    return str(inserted)


def get_priority_contact(company_id: str, db_session: Session) -> dict[str, Any] | None:
    """Return the highest-priority contact for outreach for one company."""
    rows = db_session.execute(
        text(
            """
            SELECT
                id,
                company_id,
                full_name,
                title,
                email,
                linkedin_url,
                source,
                verified,
                unsubscribed,
                created_at
            FROM contacts
            WHERE company_id = :company_id
              AND COALESCE(unsubscribed, false) = false
            """
        ),
        {"company_id": company_id},
    ).mappings().all()

    if not rows:
        return None

    def contact_rank(row: dict[str, Any]) -> tuple[int, int]:
        title = _clean_string(row.get("title"))
        title_priority = _TITLE_PRIORITY.get((title or "").lower(), 5)
        verified_priority = 0 if bool(row.get("verified")) else 1
        return (title_priority, verified_priority)

    best = min((dict(row) for row in rows), key=contact_rank)
    return best


def _resolve_company_id(company_name: str, website_domain: str, db_session: Session) -> str | None:
    domain = _clean_domain(website_domain)

    if domain:
        by_domain = db_session.execute(
            text(
                """
                SELECT id
                FROM companies
                WHERE website ILIKE :website_pattern
                ORDER BY created_at DESC
                LIMIT 1
                """
            ),
            {"website_pattern": f"%{domain}%"},
        ).scalar_one_or_none()
        if by_domain is not None:
            return str(by_domain)

    by_name = db_session.execute(
        text(
            """
            SELECT id
            FROM companies
            WHERE LOWER(name) = LOWER(:company_name)
            ORDER BY created_at DESC
            LIMIT 1
            """
        ),
        {"company_name": company_name},
    ).scalar_one_or_none()

    if by_name is None:
        return None
    return str(by_name)


def _is_target_title(title: str | None) -> bool:
    if not title:
        return False
    normalized = title.strip().lower()
    return normalized in _TARGET_TITLES


def _clean_domain(domain: str | None) -> str | None:
    if not domain:
        return None

    normalized = domain.strip().lower()
    for prefix in ("https://", "http://"):
        if normalized.startswith(prefix):
            normalized = normalized[len(prefix) :]
    if normalized.startswith("www."):
        normalized = normalized[4:]

    return normalized.split("/")[0] or None


def _clean_string(value: Any) -> str | None:
    if value is None:
        return None
    text_value = str(value).strip()
    return text_value or None
