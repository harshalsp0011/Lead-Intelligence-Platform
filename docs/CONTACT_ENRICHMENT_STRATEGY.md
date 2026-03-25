# Contact Enrichment Strategy
# Utility Lead Platform — Contact Finding Architecture

Last updated: 2026-03-23

---

## Why Contact Finding Is Hard for SMBs

The platform targets small-to-mid local businesses (healthcare staffing, manufacturing, medical
offices in Buffalo/Rochester). These companies are almost never indexed in commercial databases:

- **Hunter.io free plan** (50 searches/month): designed for tech/enterprise companies with
  public email patterns. Returns 0 results for most local SMBs.
- **Apollo people-search**: requires a paid plan ($49/mo). Free tier returns 403.
- **ZoomInfo / LeadIQ / Sales Navigator**: enterprise pricing, overkill for this use case.

The platform therefore uses a **multi-layer waterfall strategy** — free sources first,
paid APIs when available, falling back gracefully when nothing is found.

---

## Overall Goal

For each scored company the platform needs at least one of:
1. **Email address** — personalized cold email via Writer agent
2. **Phone number** — direct call by sales rep (often more effective for SMBs)

If neither is available: the company stays in the system with `contact_found=false`
and can be targeted manually via the "Add Contact" button in LeadDetail.

---

## Architecture: Waterfall Contact Finding

### Trigger Points

| Where | What runs |
|---|---|
| Pipeline page → "👤 Enrich Contacts" button | Bulk: all `scored/approved` companies |
| Pipeline page → "📞 Backfill Phones" button | Phone-only: all companies with website but no phone |
| LeadDetail → "👤 Find Contacts" button | Single company enrichment |
| Full pipeline run (Scout → Analyst → Enrich → Write) | Automatic after Analyst |

### Contact Finding Waterfall (`enrichment_client.find_contacts`)

```
For each company:
  ┌─────────────────────────────────────────────────────────────┐
  │ Step 1 — Hunter.io domain-search (if HUNTER_API_KEY set)   │
  │   API: GET /v2/domain-search?domain={domain}               │
  │   Filters: CFO, VP Finance, Facilities Mgr, Controller...  │
  │   Cost: 1 search credit (50 free/month)                    │
  │   Best for: tech companies, enterprises, national brands   │
  └─────────────────────────────────────────────────────────────┘
           │ found contacts? → SAVE + DONE
           ↓ empty
  ┌─────────────────────────────────────────────────────────────┐
  │ Step 2 — Apollo people-search (if APOLLO_API_KEY set)      │
  │   API: POST /api/v1/mixed_people/search                    │
  │   Searches by domain AND/OR company name                   │
  │   Falls back to name-only if domain missing                │
  │   Cost: requires paid plan ($49/mo)                        │
  │   Best for: larger SMBs with LinkedIn presence             │
  └─────────────────────────────────────────────────────────────┘
           │ found contacts? → SAVE + DONE
           ↓ empty
  ┌─────────────────────────────────────────────────────────────┐
  │ Step 3 — Website Scraper (free, no API key)                │
  │   Fetches: homepage + /contact + /about + /team            │
  │   Extracts: mailto: links (priority) + plain-text emails   │
  │   Skips: info@, contact@, support@, customerservice@...    │
  │   Max: 7 HTTP requests, returns up to 5 contacts           │
  └─────────────────────────────────────────────────────────────┘
           │ found emails? → EMAIL PATTERN INFERENCE (Step 3b)
           ↓
  ┌─────────────────────────────────────────────────────────────┐
  │ Step 3b — Email Pattern Inference + Hunter Verifier        │
  │   Detects naming pattern from found emails:                │
  │     tdepew@ + aevangelist@ → "first_initial_lastname"      │
  │     john.doe@ → "firstname.lastname"                       │
  │     johndoe@ → "firstname_lastname"                        │
  │                                                             │
  │   Scans contact/about page for exec name + title:          │
  │     "John Smith, CFO" → applies pattern → jsmith@domain    │
  │                                                             │
  │   Verifies with Hunter email verifier (FREE, 100/month):   │
  │     GET /v2/email-verifier?email={guessed}                 │
  │     Only saves if status = "valid" or "accept_all"         │
  │     Does NOT consume a search credit                       │
  └─────────────────────────────────────────────────────────────┘
           │ verified guess found? → SAVE as verified contact
           ↓ nothing works
           ↓ nothing works
  ┌─────────────────────────────────────────────────────────────┐
  │ Step 4 — Serper Google Search (if SERPER_API_KEY set)      │
  │   Query: "{company} CFO OR owner OR president OR CEO"      │
  │   Parses organic results + snippets for "Name, Title"      │
  │   Applies all 3 email patterns → verifies each with Hunter │
  │   Saves on first verified hit; saves unverified if no key  │
  │   Cost: 1 Serper credit (2,500 free/month)                 │
  └─────────────────────────────────────────────────────────────┘
           │ found + verified? → SAVE as serper contact
           ↓ nothing works
  ┌─────────────────────────────────────────────────────────────┐
  │ Graceful degradation: contact_found=false                  │
  │   Company still in system, visible in Leads page           │
  │   "Add Contact" button in LeadDetail for manual entry      │
  │   LinkedIn search link shown in LeadDetail header          │
  │     → https://linkedin.com/search/results/companies/?...   │
  └─────────────────────────────────────────────────────────────┘
```

### Phone Finding Waterfall (`scrape_phone_from_website`)

```
For each company with website but no phone:
  1. Fetch homepage (requests + BeautifulSoup, 10s timeout)
  2. Find <a href="tel:..."> links → most reliable, usually in header/footer
  3. Regex scan page text for (XXX) XXX-XXXX or XXX-XXX-XXXX patterns
  4. Return first valid 10/11-digit phone string
  → Stored in companies.phone
  → Shown in Leads table (clickable tel: link) + LeadDetail header
```

Phone scraping runs automatically during every enrichment run for companies missing a phone.
The "📞 Backfill Phones" button runs it in bulk for all 69 existing companies at once.

---

## Files and Their Roles

| File | Role |
|---|---|
| `agents/analyst/enrichment_client.py` | All contact + phone finding logic |
| `agents/orchestrator/orchestrator.py` | `run_contact_enrichment()` — iterates companies, calls enrichment, sets company.status + phone |
| `api/routes/triggers.py` | `/trigger/enrich` + `/trigger/backfill-phones` endpoints |
| `api/routes/leads.py` | `/leads/{id}/enrich` — per-company enrichment |
| `database/migrations/016_alter_companies_add_phone.sql` | Adds phone column |
| `database/orm_models.py` | `Company.phone` ORM field |
| `dashboard/src/pages/Pipeline.jsx` | "Enrich Contacts" + "Backfill Phones" buttons with polling |
| `dashboard/src/pages/LeadDetail.jsx` | "Find Contacts" button + phone display in header |
| `dashboard/src/pages/Leads.jsx` | Phone column in table (clickable) + CSV export |

---

## Key Functions in `enrichment_client.py`

| Function | What it does | Agentic concept |
|---|---|---|
| `find_contacts()` | Waterfall entry point — Hunter → Apollo → Website | Tool Use |
| `find_via_hunter(domain)` | Hunter domain-search, title filter | Tool Use |
| `find_via_apollo(name, domain)` | Apollo people-search, name fallback | Tool Use |
| `find_via_website(name, url)` | Scrapes contact/about/team pages | Tool Use |
| `find_via_serper(name, domain, hunter_key)` | Google search → name → pattern → verify | Tool Use + Pattern Inference + Self-Verification |
| `build_linkedin_url(company_name)` | Constructs LinkedIn company search URL | Graceful Degradation |
| `scrape_phone_from_website(url)` | Extracts phone from tel: links + regex | Tool Use |
| `_detect_email_pattern(emails)` | Infers naming convention from found emails | Pattern Inference |
| `_apply_pattern(first, last, pattern, domain)` | Generates guessed email | Pattern Inference |
| `verify_email_hunter(email)` | Confirms mailbox exists (free verifier) | Tool Use + Verification |
| `_guess_executive_email(emails, url, headers)` | Full pattern→name→guess→verify loop | Agentic Loop |
| `save_contact()` | Dedupes by email, persists to contacts table | — |
| `get_priority_contact()` | Returns best contact ranked by title priority | — |

---

## Target Titles

Contacts are only saved if their title matches one of these:

**API-sourced (Hunter/Apollo — strict):**
CFO, Chief Financial Officer, VP Finance, Director of Finance,
Director of Facilities, Facilities Manager, VP Operations,
Energy Manager, Procurement Manager, Controller

**Website-scraped (broadened — SMBs use different titles):**
All above + Owner, Co-owner, President, CEO, Chief Executive Officer,
Founder, General Manager, Office Manager, Administrator, Practice Manager,
Executive Director, Director, Principal, Partner, Managing Partner,
Regional Manager, Operations Manager, Vice President

---

## Database: Where Contact Data Lives

```
companies
  ├── phone           VARCHAR(30)   — scraped from website homepage
  ├── website         VARCHAR(500)  — used as domain source for Hunter/Apollo
  ├── contact_found   BOOL          — set TRUE when at least 1 contact saved
  └── status          VARCHAR       — set to 'enriched' when contacts found

contacts
  ├── company_id      FK → companies
  ├── full_name       VARCHAR
  ├── title           VARCHAR
  ├── email           VARCHAR       — unique, deduped on save
  ├── linkedin_url    VARCHAR
  ├── source          VARCHAR       — 'hunter' | 'apollo' | 'website_scraper'
  ├── verified        BOOL          — TRUE if Hunter verifier confirmed
  └── unsubscribed    BOOL          — set TRUE on unsubscribe event
```

---

## Steps Completed vs Planned

| Step | What | Status |
|---|---|---|
| Step 1 | Phone column + website phone scraper + backfill trigger | ✅ Done (2026-03-23) |
| Step 2 | Email pattern inference + Hunter verifier + exec name extraction | ✅ Done (2026-03-23) |
| Step 3 | Serper Google search for exec name — `"{company} CFO OR owner OR president OR CEO"` → parse name → apply all 3 patterns → verify with Hunter | ✅ Done (2026-03-23) |
| Step 4 | LinkedIn company URL — constructed from company name, shown in LeadDetail header + returned in API `linkedin_search_url` field | ✅ Done (2026-03-23) |

---

## What to Expect (Realistic Coverage)

| Source | Coverage | Notes |
|---|---|---|
| Hunter (free, 50/mo) | ~5% of SMBs | Only national/larger companies |
| Apollo (paid) | ~30–40% | Much better SMB coverage via LinkedIn |
| Website scraper | ~15–25% | Works where businesses publish emails |
| Pattern inference + verify | ~5–10% | Works when scraper finds 2+ personal emails |
| Serper Google search | ~5–15% | Finds exec name from news/press/bios, applies patterns |
| Phone scraper | ~40–60% | Most business websites have phone in header/footer |
| LinkedIn (manual) | Any | Link shown in LeadDetail → InMail or manual research |
| Manual entry | Any | "Add Contact" button in LeadDetail |

**Bottom line:** For small local businesses, phone outreach is more reliable than email.
The phone scraper (Step 1) is the highest-coverage tool in the stack.

---

## Agentic Concepts Used

| Concept | Where applied |
|---|---|
| **Tool Use** | Every external call: Hunter, Apollo, BeautifulSoup, Hunter verifier, Serper |
| **Waterfall / Conditional Fallback** | Hunter → Apollo → Website → Pattern Inference → Serper, stops at first hit |
| **Pattern Inference** | `_detect_email_pattern` — reasons about naming convention from observed data |
| **Self-verification** | `verify_email_hunter` — agent checks its own guess before committing |
| **Graceful Degradation** | Empty domain → skip Hunter; Apollo 403 → skip; no name found → LinkedIn link fallback |
| **Observation → Action** | Sees emails like `tdepew@` → infers pattern → finds name → acts (generates guess) |
| **Google as a Tool** | `find_via_serper` — treats Google search as a structured tool: query → parse → extract → act |
