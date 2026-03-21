from __future__ import annotations

"""Contact and company enrichment client for Analyst workflow.

Two distinct enrichment jobs:

1. COMPANY DATA (Apollo organization enrichment)
   enrich_company_data(domain) → employee_count, city, state
   Called by gather_company_data when site data is missing after crawling.
   Uses Apollo's free-tier organization enrichment endpoint:
     POST https://api.apollo.io/api/v1/organizations/enrich  {domain: ...}
   Returns org.num_employees, org.city, org.state.
   Requires APOLLO_API_KEY. Returns {} silently if key missing or domain unknown.

2. CONTACT FINDING (Hunter / Apollo)
   find_contacts(company_name, domain, db) → saves decision-maker emails
   Hunter: domain-search API returns CFO/VP/Facilities contacts.
   Apollo: people-search API, same filtering logic.
"""

import uuid
from typing import Any

import requests
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from config.settings import get_settings
from database.orm_models import Company, Contact

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


def enrich_company_data(domain: str) -> dict[str, Any]:
    """Call Apollo organization enrichment API and return available company signals.

    Returns a dict with any subset of:
        employee_count (int), city (str), state (str)

    Returns empty dict if APOLLO_API_KEY is missing, domain is empty,
    or Apollo has no record for the domain (404 / quota / error).

    Apollo free tier covers organization enrichment.
    API: POST https://api.apollo.io/api/v1/organizations/enrich
         Body: {"domain": "example.com"}
    """
    settings = get_settings()
    api_key = (settings.APOLLO_API_KEY or "").strip()
    clean = _clean_domain(domain)

    if not api_key or not clean:
        return {}

    try:
        response = requests.post(
            "https://api.apollo.io/api/v1/organizations/enrich",
            headers={"x-api-key": api_key, "Content-Type": "application/json"},
            json={"domain": clean},
            timeout=10,
        )
        if response.status_code in {404, 402, 422}:
            return {}
        response.raise_for_status()
        data = response.json()
    except Exception:
        return {}   # enrichment failure is never fatal

    org = data.get("organization") or {}
    result: dict[str, Any] = {}

    emp = org.get("num_employees") or org.get("estimated_num_employees")
    if emp and int(emp) > 0:
        result["employee_count"] = int(emp)

    city = _clean_string(org.get("city"))
    state = _clean_string(org.get("state"))
    if city:
        result["city"] = city
    if state:
        from agents.scout.company_extractor import normalize_state  # noqa: PLC0415
        result["state"] = normalize_state(state) or state

    return result


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

    existing: uuid.UUID | None = db_session.execute(
        select(Contact.id).where(func.lower(Contact.email) == email.lower()).limit(1)
    ).scalar()
    if existing is not None:
        return str(existing)

    provider = (get_settings().ENRICHMENT_PROVIDER or "hunter").strip().lower()

    new_id = uuid.uuid4()
    contact = Contact(
        id=new_id,
        company_id=uuid.UUID(str(company_id)) if company_id else None,
        full_name=_clean_string(contact_dict.get("full_name")),
        title=_clean_string(contact_dict.get("title")),
        email=email,
        linkedin_url=_clean_string(contact_dict.get("linkedin_url")),
        source=provider,
        verified=bool(contact_dict.get("verified") or False),
        unsubscribed=False,
    )
    db_session.add(contact)
    db_session.commit()
    return str(new_id)


def get_priority_contact(company_id: str, db_session: Session) -> dict[str, Any] | None:
    """Return the highest-priority contact for outreach for one company."""
    contacts = db_session.execute(
        select(Contact).where(
            Contact.company_id == uuid.UUID(str(company_id)),
            Contact.unsubscribed == False,  # noqa: E712
        )
    ).scalars().all()

    if not contacts:
        return None

    def contact_rank(row: dict[str, Any]) -> tuple[int, int]:
        title = _clean_string(row.get("title"))
        title_priority = _TITLE_PRIORITY.get((title or "").lower(), 5)
        verified_priority = 0 if bool(row.get("verified")) else 1
        return (title_priority, verified_priority)

    def _contact_as_dict(c: Contact) -> dict[str, Any]:
        return {
            "id": c.id,
            "company_id": c.company_id,
            "full_name": c.full_name,
            "title": c.title,
            "email": c.email,
            "linkedin_url": c.linkedin_url,
            "source": c.source,
            "verified": c.verified,
            "unsubscribed": c.unsubscribed,
            "created_at": c.created_at,
        }

    best = min((_contact_as_dict(c) for c in contacts), key=contact_rank)
    return best


def _resolve_company_id(company_name: str, website_domain: str, db_session: Session) -> str | None:
    domain = _clean_domain(website_domain)

    if domain:
        by_domain = db_session.execute(
            select(Company.id)
            .where(Company.website.ilike(f"%{domain}%"))
            .order_by(Company.created_at.desc())
            .limit(1)
        ).scalar()
        if by_domain is not None:
            return str(by_domain)

    by_name = db_session.execute(
        select(Company.id)
        .where(func.lower(Company.name) == company_name.lower())
        .order_by(Company.created_at.desc())
        .limit(1)
    ).scalar()

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
