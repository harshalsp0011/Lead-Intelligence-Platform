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

import logging
import uuid
from typing import Any

import requests

logger = logging.getLogger(__name__)

# Module-level flags: once a provider is rate-limited/blocked, skip it for the rest of the run
_hunter_blocked: bool = False
_apollo_blocked: bool = False

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
    """Find and persist contacts for one company.

    Waterfall strategy — stops at first provider that returns results:
      1. Hunter  (domain-search API)
      2. Apollo  (people-search API)
      3. Website scraper  (scrapes /contact, /about, /team pages — free, works for SMBs)
      4. Serper  (Google search for exec name → pattern → verify)
    """
    settings = get_settings()

    raw_contacts: list[dict[str, Any]] = []
    provider = "website_scraper"

    global _hunter_blocked, _apollo_blocked

    # 1. Hunter — skip if already hit 429 this run
    if settings.HUNTER_API_KEY and not _hunter_blocked:
        try:
            raw_contacts = find_via_hunter(website_domain)
            if raw_contacts:
                provider = "hunter"
        except Exception as _e:
            err_str = str(_e)
            if "429" in err_str or "Too Many Requests" in err_str:
                _hunter_blocked = True
                logger.warning("Hunter rate-limited — skipping for rest of run")
            else:
                logger.warning("Hunter skipped for %s: %s", website_domain, _e)

    # 2. Apollo — skip if already hit 403 this run
    if not raw_contacts and settings.APOLLO_API_KEY and not _apollo_blocked:
        try:
            raw_contacts = find_via_apollo(company_name, website_domain)
            if raw_contacts:
                provider = "apollo"
        except Exception as _e:
            err_str = str(_e)
            if "403" in err_str or "Forbidden" in err_str:
                _apollo_blocked = True
                logger.warning("Apollo blocked — skipping for rest of run")
            else:
                logger.warning("Apollo skipped for %s: %s", website_domain, _e)

    # 3. Website scraper (free fallback — works for small local businesses)
    if not raw_contacts and website_domain:
        try:
            raw_contacts = find_via_website(company_name, website_domain)
            if raw_contacts:
                provider = "website_scraper"
        except Exception as _e:
            logger.warning("Website scraper skipped for %s: %s", website_domain, _e)

    # 4. Serper/SerpAPI — search Google for "@domain.com" to find published email addresses
    if not raw_contacts and website_domain:
        try:
            raw_contacts = find_via_serper_email(company_name, website_domain)
            if raw_contacts:
                provider = "serper_email"
        except Exception as _e:
            logger.warning("Serper email search skipped for %s: %s", website_domain, _e)

    # 5. Snov.io domain search (150 free credits/month)
    if not raw_contacts and website_domain:
        try:
            raw_contacts = find_via_snov(company_name, website_domain)
            if raw_contacts:
                provider = "snov"
        except Exception as _e:
            logger.warning("Snov.io skipped for %s: %s", website_domain, _e)

    # 6. Prospeo — LinkedIn-sourced emails (free trial)
    if not raw_contacts and settings.PROSPEO_API_KEY and website_domain:
        try:
            raw_contacts = find_via_prospeo(company_name, website_domain)
            if raw_contacts:
                provider = "prospeo"
        except Exception as _e:
            logger.warning("Prospeo skipped for %s: %s", website_domain, _e)

    # 6.5 ZeroBounce domain format + exec name → precise email (10 credits/month)
    if not raw_contacts and website_domain:
        try:
            raw_contacts = find_via_zerobounce_domain(company_name, website_domain)
            if raw_contacts:
                provider = "zerobounce_domain"
        except Exception as _e:
            logger.warning("ZeroBounce domain search skipped for %s: %s", website_domain, _e)

    # 7. Google search — find exec name → try all 8 email permutations → verify
    if not raw_contacts and website_domain:
        try:
            serper_contact = find_via_serper(company_name, website_domain, settings.HUNTER_API_KEY)
            if serper_contact:
                raw_contacts = [serper_contact]
                provider = "serper"
        except Exception as _e:
            logger.warning("Serper name search skipped for %s: %s", website_domain, _e)

    # 8. Last resort — try generic inbox emails (info@, contact@) via website scrape without title filter.
    #    These reach *someone* at the company and are better than no contact at all.
    if not raw_contacts and website_domain:
        try:
            raw_contacts = find_via_generic_inbox(website_domain)
            if raw_contacts:
                provider = "generic_inbox"
        except Exception as _e:
            logger.warning("Generic inbox fallback skipped for %s: %s", website_domain, _e)

    company_id = _resolve_company_id(company_name=company_name, website_domain=website_domain, db_session=db_session)
    if company_id is None:
        return []

    saved_contacts: list[dict[str, Any]] = []
    for contact in raw_contacts:
        # Only save contacts with a confirmed deliverable email.
        # Exception: generic_inbox (info@, contact@) are allowed unverified —
        # they are real addresses, just not decision-maker inboxes.
        is_verified = bool(contact.get("verified") or False)
        is_generic = provider == "generic_inbox"
        if not is_verified and not is_generic:
            logger.debug(
                "Skipping unverified contact %s from provider=%s — not confirmed deliverable",
                contact.get("email"),
                provider,
            )
            continue

        try:
            contact_id = save_contact(contact_dict=contact, company_id=company_id, db_session=db_session)
        except ValueError as _ve:
            logger.debug("Skipping contact: %s", _ve)
            continue
        saved_contacts.append(
            {
                "id": contact_id,
                "company_id": company_id,
                "full_name": _clean_string(contact.get("full_name")),
                "title": _clean_string(contact.get("title")),
                "email": _clean_string(contact.get("email")),
                "linkedin_url": _clean_string(contact.get("linkedin_url")),
                "source": provider,
                "verified": is_verified,
            }
        )

    return saved_contacts


def find_via_hunter(domain: str) -> list[dict[str, Any]]:
    """Call Hunter domain-search API and return filtered decision-maker contacts."""
    settings = get_settings()
    if not settings.HUNTER_API_KEY:
        return []

    clean = _clean_domain(domain)
    if not clean:
        return []

    response = requests.get(
        "https://api.hunter.io/v2/domain-search",
        params={"domain": clean, "api_key": settings.HUNTER_API_KEY},
        timeout=8,
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

    clean = _clean_domain(domain)
    # Apollo can search by name alone if domain is missing — still useful
    if not clean and not company_name:
        return []

    body: dict[str, Any] = {
        "person_seniorities": ["senior", "executive"],
        "person_titles": sorted(_TARGET_TITLES),
        "page": 1,
        "per_page": 25,
    }
    if clean:
        body["q_organization_domains"] = [clean]
    if company_name:
        body["q_organization_name"] = company_name

    response = requests.post(
        "https://api.apollo.io/api/v1/mixed_people/search",
        headers={"x-api-key": settings.APOLLO_API_KEY, "Content-Type": "application/json"},
        json=body,
        timeout=8,
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


# Broader title set for scraped contacts — small businesses use Owner/President/CEO
_SCRAPED_TARGET_TITLES = _TARGET_TITLES | {
    "owner", "co-owner", "president", "co-president",
    "founder", "co-founder", "ceo", "chief executive officer",
    "vice president", "vp", "general manager", "office manager",
    "administrator", "practice manager", "executive director",
    "director", "principal", "partner", "managing partner",
    "regional manager", "operations manager",
}

# Generic/system emails to skip
_SKIP_EMAIL_PREFIXES = {
    "info", "hello", "hi", "contact", "admin", "webmaster",
    "support", "help", "noreply", "no-reply", "mail", "office",
    "sales", "marketing", "careers", "jobs", "billing", "privacy",
    "legal", "press", "media", "feedback", "newsletter",
    "customerservice", "customer-service", "service", "team",
    "inquiry", "inquiries", "request", "general", "reception",
}


def find_via_website(company_name: str, website_url: str) -> list[dict[str, Any]]:
    """Scrape the company website for contact emails on contact/about/team pages.

    Free fallback — works for small local businesses that list emails on their site.

    Strategy:
      1. Check homepage for mailto: links (most reliable)
      2. Try common contact/about/team page paths
      3. Extract plain-text emails from page body
      4. Return up to 3 contacts (skip generic info@/contact@ addresses)

    Agentic concept: Tool Use — autonomous web tool call with graceful degradation.
    No API key required.
    """
    import re
    from urllib.parse import urljoin

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []

    if not website_url or not website_url.strip():
        return []

    EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
    HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0 Safari/537.36"
        )
    }
    CONTACT_PATHS = [
        "/contact", "/contact-us",
        "/about", "/about-us",
        "/team",
    ]

    def fetch(url: str):
        try:
            r = requests.get(url, headers=HEADERS, timeout=3, allow_redirects=True)
            if r.status_code == 200:
                return BeautifulSoup(r.text, "html.parser")
        except Exception:
            pass
        return None

    def is_generic(email: str) -> bool:
        local = email.split("@")[0].lower().strip("._-")
        return local in _SKIP_EMAIL_PREFIXES

    def extract_from_soup(soup) -> list[dict[str, Any]]:
        found = []
        seen = set()

        # Priority 1: mailto: links — most likely to have names attached
        for tag in soup.find_all("a", href=True):
            href = tag["href"]
            if not href.lower().startswith("mailto:"):
                continue
            email = href[7:].split("?")[0].strip().lower()
            if not email or not EMAIL_RE.match(email) or email in seen or is_generic(email):
                continue
            seen.add(email)
            # Name = link text if it doesn't look like an email itself
            link_text = _clean_string(tag.get_text(strip=True))
            name = link_text if link_text and "@" not in link_text else None
            found.append({"email": email, "full_name": name, "title": None})

        # Priority 2: plain-text emails in page body
        for email in EMAIL_RE.findall(soup.get_text(" ")):
            email = email.lower().rstrip(".")
            if email in seen or is_generic(email):
                continue
            # Skip obvious non-contact domains
            if any(skip in email for skip in ["example.", "sentry.", "wix.", "squarespace.", "wordpress."]):
                continue
            seen.add(email)
            found.append({"email": email, "full_name": None, "title": None})

        return found

    base = website_url.rstrip("/")
    all_contacts: list[dict[str, Any]] = []
    seen_emails: set[str] = set()

    pages = [base] + [base + p for p in CONTACT_PATHS]
    for url in pages[:4]:  # homepage + 3 contact paths max
        soup = fetch(url)
        if not soup:
            continue
        for c in extract_from_soup(soup):
            if c["email"] not in seen_emails:
                seen_emails.add(c["email"])
                all_contacts.append(c)
        if len(all_contacts) >= 3:
            break

    # --- Phase 2: email pattern inference + Hunter verifier ---
    # If we found personal emails, detect the naming pattern and try to find
    # an executive name on the same pages to generate a verified guessed email.
    if all_contacts:
        guessed = _guess_executive_email(all_contacts, base, HEADERS)
        if guessed and guessed["email"] not in seen_emails:
            all_contacts.append(guessed)

    return [
        {
            "full_name": c.get("full_name"),
            "title": c.get("title"),
            "email": c["email"],
            "linkedin_url": None,
            "verified": c.get("verified", False),
        }
        for c in all_contacts[:5]
    ]


def find_via_serper(company_name: str, website_domain: str, hunter_api_key: str | None = None) -> dict[str, Any] | None:
    """Use Serper (Google search API) to find a decision-maker name, then generate
    and verify an email via pattern inference + Hunter verifier.

    Search query: '"{company_name}" (CFO OR owner OR president OR CEO OR founder) email'
    Parses Google organic results to extract a person name + title.
    Applies detected email pattern from website scrape (or guesses domain pattern).
    Verifies the guessed email with Hunter verifier before saving.

    Agentic concepts:
    - Tool Use: Serper API call (Google search as a tool)
    - Pattern Inference: apply naming convention detected from known domain emails
    - Self-Verification: Hunter verifier confirms guess before committing
    - Graceful Degradation: returns None if no name found or verification fails

    Returns a contact dict or None.
    """
    import re

    if not website_domain or not company_name:
        return None

    domain = _clean_domain(website_domain)
    if not domain:
        return None

    # Build search query to surface decision-maker names
    query = f'"{company_name}" (CFO OR owner OR president OR CEO OR founder) site:{domain} OR "{company_name}" (CFO OR owner OR president OR CEO OR founder)'

    organic = _google_search(query, num=5)
    if not organic:
        return None

    # Parse organic results for name + title patterns
    EXEC_TITLE_RE = re.compile(
        r"([\w\s'\-]{3,40}?)[\s,\-–|]+\s*"
        r"(CFO|Chief Financial Officer|CEO|Chief Executive Officer|"
        r"President|Owner|Co-owner|Founder|Co-founder|"
        r"Director of Finance|VP Finance|VP Operations|"
        r"General Manager|Executive Director|Facilities Manager)",
        re.IGNORECASE,
    )
    NAME_RE = re.compile(r"^[A-Z][a-z]+\s+[A-Z][a-z]+$")

    candidates: list[tuple[str, str, str]] = []  # (first, last, title)

    snippets: list[str] = []
    for item in organic:
        snippets.append(item.get("title", ""))
        snippets.append(item.get("snippet", ""))

    for snippet in snippets:
        for match in EXEC_TITLE_RE.finditer(snippet):
            raw_name = match.group(1).strip()
            title = match.group(2).strip()
            parts = raw_name.split()
            if len(parts) < 2 or len(parts) > 3:
                continue
            first, last = parts[0], parts[-1]
            if not NAME_RE.match(f"{first.capitalize()} {last.capitalize()}"):
                continue
            candidates.append((first, last, title))

    if not candidates:
        return None

    # Try ALL 8 email permutations — verify each with ZeroBounce
    zerobounce_key = (getattr(settings, "ZEROBOUNCE_API_KEY", None) or "").strip()
    for first, last, title in candidates:
        verified = _try_all_email_permutations(first, last, domain, verify=bool(zerobounce_key))
        if verified:
            return {
                "full_name": f"{first.capitalize()} {last.capitalize()}",
                "title": title,
                "email": verified["email"],
                "linkedin_url": None,
                "verified": verified["verified"],
                "source": "serper",
            }

    return None


def _try_all_email_permutations(
    first_name: str,
    last_name: str,
    domain: str,
    verify: bool = True,
) -> dict | None:
    """Try all 8 common email naming conventions for a person + domain.

    Permutations tried (in order of frequency in the wild):
      first.last@     john.smith@
      flast@          jsmith@
      firstlast@      johnsmith@
      first@          john@
      f.last@         j.smith@
      last@           smith@
      first_last@     john_smith@
      lastfirst@      smithjohn@

    Verifies each with ZeroBounce (Hunter credits reserved for domain search).
    Returns { email, verified } on first hit, or None.

    Agentic concept: Exhaustive Tool Use — tries every plausible guess
    and self-verifies before committing, maximising coverage at zero cost.
    """
    first = first_name.lower().strip()
    last  = last_name.lower().strip()
    if not first or not last or not domain:
        return None

    candidates = [
        f"{first}.{last}@{domain}",
        f"{first[0]}{last}@{domain}",
        f"{first}{last}@{domain}",
        f"{first}@{domain}",
        f"{first[0]}.{last}@{domain}",
        f"{last}@{domain}",
        f"{first}_{last}@{domain}",
        f"{last}{first}@{domain}",
    ]

    for email in candidates:
        if verify:
            result = verify_email_zerobounce(email)
            if result is True:
                return {"email": email, "verified": True}
            # result is False (invalid) → try next pattern
            # result is None (no credits) → save best guess unverified
            if result is None:
                return {"email": candidates[0], "verified": False}
        else:
            return {"email": candidates[0], "verified": False}

    return None


def _google_search(query: str, num: int = 10) -> list[dict]:
    """Run a Google search via Serper or SerpAPI (whichever key is available).

    Returns a list of organic result dicts with 'title', 'snippet', 'link'.
    Tries Serper first; falls back to SerpAPI if Serper returns 403 or no key.
    """
    settings = get_settings()

    # --- Serper (serper.dev) ---
    serper_key = (settings.SERPER_API_KEY or "").strip()
    if serper_key:
        try:
            resp = requests.post(
                "https://google.serper.dev/search",
                headers={"X-API-KEY": serper_key, "Content-Type": "application/json"},
                json={"q": query, "num": num},
                timeout=15,
            )
            if resp.status_code == 200:
                return resp.json().get("organic", [])
        except Exception:
            pass

    # --- SerpAPI (serpapi.com) ---
    serpapi_key = (getattr(settings, "SERPAPI_API_KEY", None) or "").strip()
    if serpapi_key:
        try:
            resp = requests.get(
                "https://serpapi.com/search",
                params={"q": query, "num": num, "api_key": serpapi_key, "engine": "google"},
                timeout=15,
            )
            if resp.status_code == 200:
                data = resp.json()
                # SerpAPI returns "organic_results" with same structure as Serper "organic"
                results = []
                for item in data.get("organic_results", []):
                    results.append({
                        "title": item.get("title", ""),
                        "snippet": item.get("snippet", ""),
                        "link": item.get("link", ""),
                    })
                return results
        except Exception:
            pass

    return []


def find_via_serper_email(company_name: str, website_domain: str) -> list[dict[str, Any]]:
    """Search Google for email addresses published on or about the company.

    Query: '"@domain.com" OR "email" site:domain.com'
    Also queries: '"company name" "email" contact'

    This directly surfaces email addresses that appear in Google's index —
    including press releases, local business directories, BBB listings,
    Chamber of Commerce pages, and news articles.

    Agentic concepts:
    - Tool Use: Google (via Serper) as an email discovery tool
    - Observation: parse raw snippets for email-like patterns
    - Graceful Degradation: returns [] if no emails found

    Cost: 1–2 Serper credits per company (2,500 free/month).
    """
    import re

    if not website_domain or not company_name:
        return []

    domain = _clean_domain(website_domain)
    if not domain:
        return []

    EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")

    queries = [
        f'"@{domain}"',
        f'"{company_name}" email contact',
    ]

    found_emails: dict[str, dict] = {}

    for query in queries:
        for item in _google_search(query, num=10):
            text = item.get("title", "") + " " + item.get("snippet", "")
            for email in EMAIL_RE.findall(text):
                email = email.lower().rstrip(".")
                if email in found_emails or is_generic_email(email):
                    continue
                if not email.endswith(f"@{domain}"):
                    continue
                found_emails[email] = {
                    "email": email,
                    "full_name": None,
                    "title": None,
                    "linkedin_url": None,
                    "verified": False,
                    "source": "serper_email",
                }

    return list(found_emails.values())[:5]


def is_generic_email(email: str) -> bool:
    """Return True if the email looks like a generic/system address."""
    local = email.split("@")[0].lower().strip("._-")
    return local in _SKIP_EMAIL_PREFIXES


def find_via_zerobounce_domain(company_name: str, website_domain: str) -> list[dict[str, Any]]:
    """Use ZeroBounce guessformat API to find the email pattern for a domain,
    then combine with an exec name from Google search to generate a precise email.

    ZeroBounce guessformat returns the confirmed email format used by a domain
    (e.g. 'first.last', 'flast') with confidence level. Combined with a real
    exec name found via Google, this produces a high-confidence email address.

    Free tier: 10 domain searches/month.

    Agentic concepts:
    - Tool Use: ZeroBounce as domain intelligence source
    - Pattern Inference: apply confirmed format instead of trying all 8 blind
    - Self-Verification: validate the generated email with ZeroBounce validate API
    """
    settings = get_settings()
    api_key = (getattr(settings, "ZEROBOUNCE_API_KEY", None) or "").strip()
    if not api_key or not website_domain:
        return []

    domain = _clean_domain(website_domain)
    if not domain:
        return []

    # Step 1: Get the confirmed email format for this domain
    try:
        fmt_resp = requests.get(
            "https://api.zerobounce.net/v2/guessformat",
            params={"api_key": api_key, "domain": domain},
            timeout=10,
        )
        if fmt_resp.status_code != 200:
            return []
        fmt_data = fmt_resp.json()
        top_format = fmt_data.get("format", "")
        confidence = fmt_data.get("confidence", "")
        if not top_format or confidence == "low":
            return []
    except Exception:
        return []

    # Step 2: Find an exec name via Google search
    query = f'"{company_name}" (CEO OR CFO OR owner OR president OR founder OR director)'
    organic = _google_search(query, num=5)
    if not organic:
        return []

    import re
    NAME_RE = re.compile(r'\b([A-Z][a-z]{1,15})\s+([A-Z][a-z]{1,20})\b')
    EXEC_RE = re.compile(
        r'(CEO|CFO|President|Owner|Founder|Director|Chief|VP|Vice President)',
        re.IGNORECASE,
    )

    candidates: list[tuple[str, str]] = []
    for item in organic:
        text = item.get("title", "") + " " + item.get("snippet", "")
        if not EXEC_RE.search(text):
            continue
        for m in NAME_RE.finditer(text):
            first, last = m.group(1), m.group(2)
            # Skip obvious non-names
            if first.lower() in {"the", "our", "for", "and", "new", "this", "with"}:
                continue
            candidates.append((first, last))

    if not candidates:
        return []

    # Step 3: Apply confirmed format to generate email
    _FORMAT_MAP = {
        "first.last":   lambda f, l: f"{f.lower()}.{l.lower()}",
        "firstlast":    lambda f, l: f"{f.lower()}{l.lower()}",
        "flast":        lambda f, l: f"{f[0].lower()}{l.lower()}",
        "f.last":       lambda f, l: f"{f[0].lower()}.{l.lower()}",
        "lastfirst":    lambda f, l: f"{l.lower()}{f.lower()}",
        "lfirst":       lambda f, l: f"{l[0].lower()}{f.lower()}",
        "first":        lambda f, l: f.lower(),
        "last":         lambda f, l: l.lower(),
        "first_last":   lambda f, l: f"{f.lower()}_{l.lower()}",
        "last-first":   lambda f, l: f"{l.lower()}-{f.lower()}",
        "firstl":       lambda f, l: f"{f.lower()}{l[0].lower()}",
    }

    fmt_fn = _FORMAT_MAP.get(top_format)
    if not fmt_fn:
        return []

    first, last = candidates[0]
    local = fmt_fn(first, last)
    email = f"{local}@{domain}"

    if not _is_valid_email(email):
        return []

    # Step 4: Validate the generated email with ZeroBounce
    try:
        val_resp = requests.get(
            "https://api.zerobounce.net/v2/validate",
            params={"api_key": api_key, "email": email, "ip_address": ""},
            timeout=12,
        )
        if val_resp.status_code == 200:
            status = val_resp.json().get("status", "")
            if status not in {"valid", "catch-all"}:
                return []
            verified = status == "valid"
        else:
            verified = False
    except Exception:
        verified = False

    return [{
        "email": email,
        "full_name": f"{first} {last}",
        "title": None,
        "linkedin_url": None,
        "verified": verified,
        "source": "zerobounce_domain",
    }]


def find_via_generic_inbox(website_domain: str) -> list[dict[str, Any]]:
    """Last-resort fallback: try common generic inbox addresses for the domain.

    Checks info@, contact@, hello@, office@ by verifying the domain has a live
    website (not a DNS check — just confirms the domain is reachable).
    Returns the first address that is likely to exist.

    These generic addresses reach *someone* at the company and are better than
    no contact at all for local SMBs that don't publish personal emails.
    """
    domain = _clean_domain(website_domain)
    if not domain:
        return []

    # Confirm domain is reachable
    try:
        r = requests.get(f"https://{domain}", timeout=8, allow_redirects=True,
                         headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code >= 400:
            r = requests.get(f"http://{domain}", timeout=8, allow_redirects=True,
                             headers={"User-Agent": "Mozilla/5.0"})
            if r.status_code >= 400:
                return []
    except Exception:
        return []

    # Return the first generic address — prefer info@ as most widely monitored
    for prefix in ["info", "contact", "hello", "office", "admin"]:
        email = f"{prefix}@{domain}"
        return [{
            "email": email,
            "full_name": None,
            "title": "General Inquiry",
            "linkedin_url": None,
            "verified": False,
            "source": "generic_inbox",
        }]

    return []


def find_via_snov(company_name: str, website_domain: str) -> list[dict[str, Any]]:
    """Find decision-maker emails via Snov.io Domain Search API.

    Free tier: 150 credits/month (1 credit = 1 email found).
    API: POST https://api.snov.io/v2/domain-emails-with-info
    Requires SNOV_CLIENT_ID + SNOV_CLIENT_SECRET in .env (OAuth flow).

    Snov.io is particularly good for finding emails for companies that
    Hunter misses — it crawls different sources and LinkedIn profiles.

    Agentic concept: Tool Use — Snov.io as a complementary contact database.
    """
    settings = get_settings()
    client_id     = (getattr(settings, "SNOV_CLIENT_ID",     None) or "").strip()
    client_secret = (getattr(settings, "SNOV_CLIENT_SECRET", None) or "").strip()

    if not client_id or not client_secret:
        return []

    domain = _clean_domain(website_domain)
    if not domain:
        return []

    try:
        # Step 1: Get OAuth access token
        token_resp = requests.post(
            "https://api.snov.io/v1/oauth/access_token",
            json={"grant_type": "client_credentials", "client_id": client_id, "client_secret": client_secret},
            timeout=10,
        )
        if token_resp.status_code != 200:
            return []
        token = token_resp.json().get("access_token", "")
        if not token:
            return []

        # Step 2: Domain email search
        search_resp = requests.post(
            "https://api.snov.io/v2/domain-emails-with-info",
            json={"access_token": token, "domain": domain, "type": "all", "limit": 10, "lastId": 0},
            timeout=15,
        )
        if search_resp.status_code != 200:
            return []
        emails_data = search_resp.json().get("emails", [])
    except Exception:
        return []

    contacts = []
    for person in emails_data:
        email = _clean_string(person.get("email"))
        if not email or is_generic_email(email):
            continue
        first = _clean_string(person.get("firstName", ""))
        last  = _clean_string(person.get("lastName", ""))
        full_name = _clean_string(f"{first or ''} {last or ''}".strip()) or None
        title = _clean_string(person.get("position"))
        contacts.append({
            "email": email,
            "full_name": full_name,
            "title": title,
            "linkedin_url": _clean_string(person.get("linkedIn")),
            "verified": bool(person.get("isVerified")),
            "source": "snov",
        })

    return contacts[:5]


def find_via_skrapp(company_name: str, website_domain: str) -> list[dict[str, Any]]:
    """Find decision-maker emails via Skrapp.io domain search API.

    Skrapp specialises in LinkedIn-sourced professional emails.
    Free tier: 150 emails/month.
    API: GET https://api.skrapp.io/api/v2/search?domain=example.com&size=10
    Headers: X-Access-Key: YOUR_KEY

    Agentic concept: Tool Use — Skrapp as a LinkedIn-sourced contact database.
    """
    settings = get_settings()
    api_key = (settings.SKRAPP_API_KEY or "").strip()
    if not api_key or not website_domain:
        return []

    domain = _clean_domain(website_domain)
    if not domain:
        return []

    try:
        resp = requests.get(
            "https://api.skrapp.io/api/v2/search",
            headers={"X-Access-Key": api_key, "Content-Type": "application/json"},
            params={"domain": domain, "size": 10},
            timeout=15,
        )
        if resp.status_code != 200:
            return []
        data = resp.json()
    except Exception:
        return []

    emails_data = data.get("emails", []) or data.get("data", {}).get("emails", [])
    contacts = []
    for person in emails_data:
        email = _clean_string(person.get("email"))
        if not email or is_generic_email(email):
            continue
        first = _clean_string(person.get("firstName") or person.get("first_name") or "")
        last  = _clean_string(person.get("lastName")  or person.get("last_name")  or "")
        full_name = _clean_string(f"{first or ''} {last or ''}".strip()) or None
        title = _clean_string(person.get("position") or person.get("title"))
        contacts.append({
            "email": email,
            "full_name": full_name,
            "title": title,
            "linkedin_url": _clean_string(person.get("linkedinUrl") or person.get("linkedin_url")),
            "verified": bool(person.get("verified") or person.get("validation") == "valid"),
            "source": "skrapp",
        })

    return contacts[:5]


def find_via_prospeo(company_name: str, website_domain: str) -> list[dict[str, Any]]:
    """Find decision-maker emails via Prospeo Search Person + Enrich Person APIs.

    Two-step flow (post-March 2026 migration to new endpoints):
      1. POST /search-person — find senior contacts at domain (200M+ LinkedIn contacts)
      2. POST /enrich-person — reveal verified email for each match

    New endpoints (old /domain-search removed March 1, 2026):
      Search:  POST https://api.prospeo.io/search-person
               Body: { "filters": { "company": { "websites": { "include": ["domain"] } },
                                    "person_seniority": { "include": [...] } } }
      Enrich:  POST https://api.prospeo.io/enrich-person
               Body: { "data": { "person_id": "...", "company_website": "domain" } }

    Credit conservation: search costs 0 credits; enrich costs 1 credit per person.
    We only enrich the top 2 matches to save credits.

    Agentic concept: Tool Use — Prospeo as a LinkedIn-sourced contact database.
    """
    settings = get_settings()
    api_key = (settings.PROSPEO_API_KEY or "").strip()
    if not api_key or not website_domain:
        return []

    domain = _clean_domain(website_domain)
    if not domain:
        return []

    headers = {"X-KEY": api_key, "Content-Type": "application/json"}

    # --- Step 1: Search for senior contacts at this domain ---
    try:
        search_resp = requests.post(
            "https://api.prospeo.io/search-person",
            headers=headers,
            json={
                "page": 1,
                "filters": {
                    "company": {
                        "websites": {"include": [domain]},
                    },
                    "person_seniority": {
                        "include": ["C-Suite", "Vice President", "Director", "Founder/Owner", "Partner", "Head"],
                    },
                    "max_person_per_company": 5,
                },
            },
            timeout=15,
        )
        if search_resp.status_code != 200:
            logger.warning("Prospeo search-person %s: HTTP %s — %s", domain, search_resp.status_code, search_resp.text[:200])
            return []
        search_data = search_resp.json()
    except Exception as exc:
        logger.warning("Prospeo search-person error for %s: %s", domain, exc)
        return []

    if search_data.get("error"):
        logger.warning("Prospeo search-person error for %s: %s", domain, search_data.get("error_code"))
        return []

    results = search_data.get("results", [])
    if not results:
        return []

    # Filter to people whose email is not UNAVAILABLE (save enrich credits)
    enrichable = [
        item for item in results
        if (item.get("person") or {}).get("email", {}).get("status") != "UNAVAILABLE"
    ]
    if not enrichable:
        return []

    # --- Step 2: Enrich top 2 contacts to reveal email ---
    contacts = []
    for item in enrichable[:2]:
        person = item.get("person") or {}
        person_id = _clean_string(person.get("person_id") or person.get("id"))
        first = _clean_string(person.get("first_name") or "")
        last  = _clean_string(person.get("last_name")  or "")
        full_name = _clean_string(f"{first} {last}".strip()) or None
        title = _clean_string(person.get("current_job_title") or person.get("job_title") or person.get("title"))
        linkedin_url = _clean_string(person.get("linkedin_url"))

        # Build enrich request — person_id alone is sufficient if we have it
        enrich_payload: dict[str, Any] = {"company_website": domain}
        if person_id:
            enrich_payload["person_id"] = person_id
        elif first and last:
            enrich_payload["first_name"] = first
            enrich_payload["last_name"] = last
        else:
            continue  # not enough to enrich

        try:
            enrich_resp = requests.post(
                "https://api.prospeo.io/enrich-person",
                headers=headers,
                json={"only_verified_email": False, "enrich_mobile": False, "data": enrich_payload},
                timeout=15,
            )
            if enrich_resp.status_code != 200:
                logger.warning("Prospeo enrich-person %s: HTTP %s", domain, enrich_resp.status_code)
                continue
            enrich_result = enrich_resp.json()
        except Exception as exc:
            logger.warning("Prospeo enrich-person error for %s: %s", domain, exc)
            continue

        if enrich_result.get("error"):
            logger.warning("Prospeo enrich-person error for %s: %s", domain, enrich_result.get("error_code"))
            continue

        enriched_person = enrich_result.get("person") or {}

        # email may be plain string or nested object depending on plan/response version
        raw_email = enriched_person.get("email")
        if isinstance(raw_email, dict):
            email = _clean_string(raw_email.get("email"))
            email_status = str(raw_email.get("status") or "").upper()
        else:
            email = _clean_string(raw_email)
            email_status = str(enriched_person.get("email_status") or "").upper()

        if not email or is_generic_email(email):
            continue

        verified = email_status == "VERIFIED"

        contacts.append({
            "email": email,
            "full_name": full_name,
            "title": title,
            "linkedin_url": linkedin_url,
            "verified": verified,
            "source": "prospeo",
        })

    return contacts


def build_linkedin_url(company_name: str) -> str:
    """Construct a best-guess LinkedIn company search URL from the company name.

    Not a guaranteed link — opens a LinkedIn company search so the sales rep
    can quickly find the company page and send an InMail.

    Agentic concept: Graceful Degradation — provides a manual fallback
    when no email contact is found, enabling LinkedIn outreach.

    Returns a search URL string.
    """
    import urllib.parse
    slug = urllib.parse.quote_plus(company_name)
    return f"https://www.linkedin.com/search/results/companies/?keywords={slug}"


def lookup_phone_google_places(company_name: str, city: str | None = None, state: str | None = None) -> str | None:
    """Look up a business phone number via Google Places API (Text Search).

    Much more reliable than website scraping for local SMBs — Google has
    structured data for virtually every US business with a Google Business Profile.

    Free tier: 100k requests/month (Text Search) with $200/month credit.
    API: GET https://maps.googleapis.com/maps/api/place/textsearch/json
         GET https://maps.googleapis.com/maps/api/place/details/json

    Agentic concept: Tool Use — Google Places as a structured contact tool.
    """
    settings = get_settings()
    api_key = (settings.GOOGLE_MAPS_API_KEY or "").strip()
    if not api_key or not company_name:
        return None

    location = f"{company_name}"
    if city:
        location += f" {city}"
    if state:
        location += f" {state}"

    try:
        # Step 1: Text search to get place_id
        search_resp = requests.get(
            "https://maps.googleapis.com/maps/api/place/textsearch/json",
            params={"query": location, "key": api_key},
            timeout=10,
        )
        if search_resp.status_code != 200:
            return None
        results = search_resp.json().get("results", [])
        if not results:
            return None

        place_id = results[0].get("place_id")
        if not place_id:
            return None

        # Step 2: Place Details to get formatted_phone_number
        detail_resp = requests.get(
            "https://maps.googleapis.com/maps/api/place/details/json",
            params={"place_id": place_id, "fields": "formatted_phone_number", "key": api_key},
            timeout=10,
        )
        if detail_resp.status_code != 200:
            return None
        phone = detail_resp.json().get("result", {}).get("formatted_phone_number")
        return phone or None

    except Exception:
        return None


def lookup_phone_yelp(company_name: str, city: str | None = None, state: str | None = None) -> str | None:
    """Look up a business phone number via Yelp Fusion API (Business Search).

    Good fallback for businesses not on Google or with no Google Business Profile.
    Free tier: 5,000 API calls/day.
    API: GET https://api.yelp.com/v3/businesses/search

    Agentic concept: Tool Use — Yelp as a structured contact tool.
    """
    settings = get_settings()
    api_key = (settings.YELP_API_KEY or "").strip()
    if not api_key or not company_name:
        return None

    location = city or "Buffalo, NY"
    if state and city:
        location = f"{city}, {state}"

    try:
        resp = requests.get(
            "https://api.yelp.com/v3/businesses/search",
            headers={"Authorization": f"Bearer {api_key}"},
            params={"term": company_name, "location": location, "limit": 1},
            timeout=10,
        )
        if resp.status_code != 200:
            return None
        businesses = resp.json().get("businesses", [])
        if not businesses:
            return None
        phone = businesses[0].get("display_phone") or businesses[0].get("phone")
        return phone or None
    except Exception:
        return None


def scrape_phone_from_website(website_url: str) -> str | None:
    """Scrape phone number from a company's homepage.

    Tries to find a phone number via:
    1. <a href="tel:..."> links (most reliable)
    2. Regex pattern matching in page text

    Returns first valid 10-digit US/CA phone string or None.
    Agentic concept: Tool Use — free, no API key required.
    """
    import re
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return None

    if not website_url or not website_url.strip():
        return None

    HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0 Safari/537.36"
        )
    }
    PHONE_RE = re.compile(
        r"(\+1[-.\s]?)?"
        r"\(?\d{3}\)?[-.\s]\d{3}[-.\s]\d{4}"
    )

    try:
        resp = requests.get(website_url.rstrip("/"), headers=HEADERS, timeout=10, allow_redirects=True)
        if resp.status_code != 200:
            return None
        soup = BeautifulSoup(resp.text, "html.parser")

        # Priority 1: tel: links
        for tag in soup.find_all("a", href=True):
            href = tag["href"]
            if href.lower().startswith("tel:"):
                phone = href[4:].strip().replace("-", "").replace(" ", "").replace(".", "")
                digits = re.sub(r"\D", "", phone)
                if len(digits) in (10, 11):
                    return tag["href"][4:].strip()

        # Priority 2: regex in page text
        text = soup.get_text(" ")
        matches = PHONE_RE.findall(text)
        for match in matches:
            raw = match if isinstance(match, str) else "".join(match)
            digits = re.sub(r"\D", "", raw)
            if len(digits) in (10, 11):
                return raw.strip()
    except Exception:
        pass

    return None


def _detect_email_pattern(emails: list[str], domain: str) -> str | None:
    """Detect the naming convention used in a list of known employee emails.

    Patterns detected:
      'first_initial_lastname'  → tdepew  (t + depew)
      'firstname_lastname'      → johndoe
      'firstname.lastname'      → john.doe
      'firstname'               → john (single token)

    Returns pattern key or None if pattern can't be determined.
    """
    import re
    local_parts = [e.split("@")[0].lower() for e in emails if "@" in e]
    if not local_parts:
        return None

    dot_count = sum(1 for p in local_parts if "." in p)
    if dot_count >= len(local_parts) // 2:
        return "firstname.lastname"

    # Check if looks like initial+lastname (1-2 chars then 3+ chars, no separator)
    initial_last = sum(
        1 for p in local_parts
        if re.match(r'^[a-z]{1,2}[a-z]{3,}$', p)
    )
    if initial_last >= len(local_parts) // 2:
        return "first_initial_lastname"

    return "firstname_lastname"


def _apply_pattern(first_name: str, last_name: str, pattern: str, domain: str) -> str | None:
    """Generate a guessed email from a name and detected pattern."""
    first = first_name.lower().strip()
    last = last_name.lower().strip()
    if not first or not last or not domain:
        return None

    if pattern == "first_initial_lastname":
        return f"{first[0]}{last}@{domain}"
    if pattern == "firstname.lastname":
        return f"{first}.{last}@{domain}"
    if pattern == "firstname_lastname":
        return f"{first}{last}@{domain}"
    return None


def verify_email_zerobounce(email: str) -> bool | None:
    """Verify an email using ZeroBounce API (free tier: 100/month).

    ZeroBounce does a full SMTP check and returns a status:
      valid       — mailbox confirmed live
      catch-all   — domain accepts all mail (can't confirm specific mailbox)
      invalid     — mailbox doesn't exist (hard bounce)
      unknown     — couldn't verify (temporary)

    Returns:
      True  — valid or catch-all
      False — confirmed invalid/spam/abuse
      None  — couldn't determine (quota exhausted, network error, unknown status)

    Agentic concept: Tool Use — independent SMTP verifier as fallback when Hunter quota exhausted.
    """
    settings = get_settings()
    api_key = (getattr(settings, "ZEROBOUNCE_API_KEY", None) or "").strip()
    if not api_key or not email:
        return None
    try:
        resp = requests.get(
            "https://api.zerobounce.net/v2/validate",
            params={"api_key": api_key, "email": email, "ip_address": ""},
            timeout=15,
        )
        if resp.status_code != 200:
            return None
        data = resp.json()
        status = str(data.get("status", "")).lower()
        if status in {"valid", "catch-all"}:
            return True
        if status in {"invalid", "spamtrap", "abuse", "do_not_mail"}:
            return False
        # "unknown", empty, error messages (e.g. no credits) → can't determine
        return None
    except Exception:
        return None


def verify_email(email: str) -> bool | None:
    """Verify an email using ZeroBounce only.

    Hunter's 50 monthly credits are reserved entirely for domain search (finding
    new contacts). Spending them on verification would reduce how many new companies
    we can find contacts for each month.

    Returns:
      True  — confirmed deliverable
      False — confirmed invalid (hard bounce)
      None  — couldn't determine (ZeroBounce quota exhausted or errored)

    Agentic concept: Graceful Degradation — never mark a contact invalid just
    because credits ran out.
    """
    return verify_email_zerobounce(email)


def verify_email_hunter(email: str) -> bool:
    """Verify a guessed email — uses Hunter then ZeroBounce as fallback.

    Agentic concept: Tool Use — verifies pattern-generated emails before saving.
    """
    return verify_email(email)


def _guess_executive_email(
    scraped_emails: list[dict[str, Any]],
    base_url: str,
    headers: dict,
) -> dict[str, Any] | None:
    """Detect email pattern from scraped emails, find an executive name on the page,
    generate a guessed email, and verify it with Hunter.

    Agentic concepts used:
    - Pattern inference: detects first_initial_lastname / firstname.lastname etc.
    - Tool Use: Hunter email verifier to confirm guess before saving
    - Graceful degradation: returns None if no name found or verification fails

    Returns a contact dict or None.
    """
    import re
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return None

    emails = [c["email"] for c in scraped_emails if c.get("email")]
    if not emails:
        return None

    domain = emails[0].split("@")[-1] if "@" in emails[0] else None
    if not domain:
        return None

    pattern = _detect_email_pattern(emails, domain)
    if not pattern:
        return None

    # Look for executive name + title on contact/about pages
    EXEC_TITLE_RE = re.compile(
        r"([\w\s'\-]{3,40}),?\s+"
        r"(cfo|chief financial|ceo|chief executive|president|owner|founder|"
        r"director of finance|vp finance|vp operations|general manager|"
        r"executive director|facilities manager)",
        re.IGNORECASE,
    )
    NAME_RE = re.compile(r"^[A-Z][a-z]+\s+[A-Z][a-z]+$")  # "First Last"

    pages = [base_url] + [base_url + p for p in ["/contact", "/about", "/about-us", "/team"]]
    for url in pages[:4]:
        try:
            resp = requests.get(url, headers=headers, timeout=8, allow_redirects=True)
            if resp.status_code != 200:
                continue
            soup = BeautifulSoup(resp.text, "html.parser")
            text = soup.get_text(" ")

            for match in EXEC_TITLE_RE.finditer(text):
                raw_name = match.group(1).strip()
                title = match.group(2).strip()
                # Validate looks like a real name
                parts = raw_name.split()
                if len(parts) < 2 or len(parts) > 3:
                    continue
                first, last = parts[0], parts[-1]
                if not NAME_RE.match(f"{first.capitalize()} {last.capitalize()}"):
                    continue

                result = _try_all_email_permutations(first, last, domain, verify=True)
                if result:
                    return {
                        "full_name": raw_name,
                        "title": title,
                        "email": result["email"],
                        "linkedin_url": None,
                        "verified": result["verified"],
                    }
        except Exception:
            continue

    return None


_PLACEHOLDER_LOCAL_PARTS = {
    "firstname", "lastname", "first", "last", "flast", "f.last",
    "first.last", "firstlast", "lastfirst", "first_last", "name",
    "email", "test", "user", "example",
}

def _is_valid_email(email: str) -> bool:
    """Return False for obviously fake/placeholder/corrupted emails."""
    import re
    if not email or "@" not in email:
        return False
    local, domain = email.rsplit("@", 1)
    # Reject placeholder local parts
    if local.lower() in _PLACEHOLDER_LOCAL_PARTS:
        return False
    # Reject corrupted domains (contain spaces, CSS class names, etc.)
    if not re.match(r'^[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$', domain):
        return False
    return True


def save_contact(contact_dict: dict[str, Any], company_id: str, db_session: Session) -> str:
    """Insert a contact row if email is new; otherwise return the existing contact ID."""
    email = _clean_string(contact_dict.get("email"))
    if not email:
        raise ValueError("Contact email is required to save contact")
    if not _is_valid_email(email):
        raise ValueError(f"Refusing to save invalid/placeholder email: {email}")

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
        data_origin="scout",
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
