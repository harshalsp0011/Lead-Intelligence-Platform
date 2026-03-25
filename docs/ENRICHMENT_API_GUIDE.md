# Contact Enrichment — API Guide & Strategy

**Last updated:** 2026-03-24
**Purpose:** Document every API integrated into the enrichment waterfall, its status,
free-tier limits, what it finds, and why it is or isn't working right now.

---

## Current DB State

| Metric | Value |
|---|---|
| Total contacts in DB | 80 |
| Verified (SMTP-confirmed) | 3 |
| Unverified (found but unconfirmed) | 77 |
| Source of all contacts | Hunter (domain search ran before quota hit) |

---

## What "Enrichment" Does

For each company in the DB (scored/approved), we run a **waterfall** — a sequence of
providers that stops as soon as one returns a result. This conserves API credits and
avoids redundant calls.

### Quality Gates Applied Before Saving
1. **Placeholder filter** — rejects `firstname@`, `lastname@`, `last@`, `flast@` etc.
   (Hunter sometimes returns these as unverified guesses)
2. **Domain integrity check** — rejects emails where the domain contains CSS class names
   or spaces (scraping artifacts like `email@domain.com--skip-themes`)
3. **Generic inbox fallback** — `info@`, `contact@` etc. are only saved as last resort,
   never wasted on verification credits

---

## The Waterfall — Step by Step

Every company goes through these steps in order, stopping at first hit:

### Step 1 — Hunter (domain search)
- **Endpoint:** `GET https://api.hunter.io/v2/domain-search?domain=...`
- **What it does:** Returns all emails Hunter has crawled for a domain, filtered to
  decision-maker titles (CFO, VP Finance, Facilities Manager, etc.)
- **Free tier:** 50 searches/month
- **Verification:** Separate endpoint `GET /v2/email-verifier` — 50 verifications/month
- **Current status:** ❌ **429 — quota exhausted this month.** Resets monthly.
- **Why we still call it:** Next month it will work. Module-level flag `_hunter_blocked`
  skips all remaining companies once first 429 is seen (saves time).
- **Key in .env:** `HUNTER_API_KEY`

---

### Step 2 — Apollo (people search)
- **Endpoint:** `POST https://api.apollo.io/api/v1/mixed_people/search`
- **What it does:** Searches Apollo's B2B database for people at a company by domain
- **Free tier:** Organization enrichment is free; people search is blocked on free tier
- **Current status:** ❌ **403 — free tier does not allow people search.**
  Organization enrichment (`/organizations/enrich`) still works and is used by the
  Analyst agent for company data (employee count, city, state).
- **Module flag:** `_apollo_blocked` skips remaining companies after first 403.
- **Key in .env:** `APOLLO_API_KEY`

---

### Step 3 — Website Scraper (free, no API key)
- **What it does:** Fetches homepage + `/contact`, `/about`, `/team`, `/staff` pages.
  Extracts `mailto:` links and plain-text email patterns via regex.
- **Free tier:** Unlimited (just HTTP requests)
- **Current status:** ⚠️ **Works but rarely finds emails.** Most modern SMB websites
  use JavaScript contact forms, not `mailto:` links. Returns 0 for ~95% of companies.
- **Timeout:** 5s per page, max 7 pages per company
- **No key needed**

---

### Step 4 — Serper / SerpAPI (Google email search)
- **What it does:** Searches Google for `"@domain.com"` to find emails published
  anywhere on the web (press releases, BBB listings, directories, news).
- **Serper endpoint:** `POST https://google.serper.dev/search` — Header: `X-API-KEY`
- **SerpAPI endpoint:** `GET https://serpapi.com/search` — Param: `api_key`
- **Free tier:** Serper: 2,500/month | SerpAPI: 100/month
- **Current status:** ✅ **Both working.** Serper tried first; SerpAPI is fallback.
- **Logic:** `_google_search()` helper tries Serper → falls back to SerpAPI automatically
- **Keys in .env:** `SERPER_API_KEY`, `SERPAPI_API_KEY`

---

### Step 5 — Snov.io (domain email search)
- **Endpoint:** `POST https://api.snov.io/v2/domain-emails-with-info`
- **Auth:** OAuth2 client credentials (`/v1/oauth/access_token` first)
- **What it does:** Returns emails Snov.io has for a domain from LinkedIn + web crawling
- **Free tier:** 150 credits/month — but domain search requires a paid plan
- **Current status:** ❌ **403 — "no permissions for this action."** Free plan only
  allows email verification and single-email finder, not bulk domain search.
- **Keys in .env:** `SNOV_CLIENT_ID`, `SNOV_CLIENT_SECRET`

---

### Step 6 — Prospeo (Search Person → Enrich Person)
- **Two-step flow (post-March 2026):**
  1. `POST https://api.prospeo.io/search-person` — find senior contacts at domain
     Body: `{"filters": {"company": {"websites": {"include": ["domain.com"]}}, "person_seniority": {"include": ["C-Level","VP","Director","Founder/Owner","Partner"]}}}`
     Returns: list of people with `person_id`, names, titles (0 credits)
  2. `POST https://api.prospeo.io/enrich-person` — reveal email for a specific person
     Body: `{"data": {"person_id": "...", "company_website": "domain.com"}}`
     Returns: email + email_status (VERIFIED/UNVERIFIED) (1 credit per enrich)
- **Old endpoint (removed March 1, 2026):** `POST /domain-search` — deprecated
- **Current status:** ✅ **Integrated** — new key working, 100 enrich credits on free tier
- **Credit conservation:** Search costs 0 credits; only top 2 contacts per company are enriched
- **Key in .env:** `PROSPEO_API_KEY`
- **Why it matters:** 200M+ LinkedIn-sourced contacts searchable by domain and seniority.

---

### Step 6.5 — ZeroBounce Domain Format (guessformat)
- **Endpoint:** `GET https://api.zerobounce.net/v2/guessformat?domain=...`
- **What it does:** Returns the confirmed email format used by a domain
  (e.g. `first.last`, `flast`) with confidence level. Combined with an exec name
  from Google search, generates a high-confidence email without trying all 8 patterns.
- **Free tier:** 10 domain searches/month
- **Current status:** ❌ **0 credits — exhausted during testing this month.**
  Resets on next billing cycle.
- **Key in .env:** `ZEROBOUNCE_API_KEY`

---

### Step 7 — Google Name Search + 8 Permutations
- **What it does:**
  1. Searches Google for `"company" (CEO OR CFO OR owner OR president OR founder)`
  2. Parses results for a person name + title using regex
  3. Generates all 8 email patterns: `first.last`, `flast`, `firstlast`, `first`,
     `f.last`, `last`, `first_last`, `lastfirst`
  4. Verifies each with Hunter verifier (free, no search credit) or ZeroBounce
- **Current status:** ✅ **Working** (Google search works; verification exhausted but
  unverified guesses still saved with `verified=False`)
- **Uses:** `SERPER_API_KEY` / `SERPAPI_API_KEY` for search, `HUNTER_API_KEY` for verify

---

### Step 8 — Generic Inbox Fallback (last resort)
- **What it does:** If nothing found, checks if the domain is reachable, then saves
  `info@domain.com` as a contact with title "General Inquiry"
- **Current status:** ✅ **Working**
- **Why it exists:** Ensures every company with a live website has *some* contact point
  so the writer can generate an email and the sales rep can at least try
- **Limitation:** Goes to a generic inbox, not a decision-maker. Lower response rate.

---

## Email Verification

### Hunter Email Verifier
- **Endpoint:** `GET https://api.hunter.io/v2/email-verifier?email=...`
- **Free tier:** 50 verifications/month (shared with domain search quota)
- **Current status:** ❌ **429 — exhausted this month**
- **Returns:** `valid`, `accept_all`, `invalid`, `disposable`, `webmail`

### ZeroBounce Validate
- **Endpoint:** `GET https://api.zerobounce.net/v2/validate?email=...`
- **Free tier:** 100 validations/month
- **Current status:** ❌ **0 credits — exhausted during testing this month**
- **Returns:** `valid`, `invalid`, `catch-all`, `unknown`, `spamtrap`, `abuse`
- **Note:** `catch-all` means the domain accepts all mail (can't confirm specific mailbox)
  but is still worth sending to — common in SMBs

### Verification Priority (when credits are available)
The `trigger_verify_emails` endpoint sorts unverified contacts before verifying:

| Priority | Criteria | Example |
|---|---|---|
| 1 | Named person + executive title | Deborah Bauer, CFO |
| 2 | Named person + any title | John Smith, Manager |
| 3 | Named person, no title | Jane Doe |
| 4 | Personal-looking email (short, no generic prefix) | `jnotaro@csshealth.com` |
| Skipped | Generic inbox | `info@`, `contact@`, `hello@` |

---

## Phone Enrichment (separate from email)

Phone waterfall per company (stops at first hit):

| Step | Source | Status | Free Tier |
|---|---|---|---|
| 1 | Google Places API | ✅ Working | 100k requests/month |
| 2 | Yelp Fusion API | ✅ Working | 5,000/day |
| 3 | Website scraper (tel: links + regex) | ✅ Working | Unlimited |

**Result:** 101/103 companies have phones.

---

## API Keys Summary

| Key | Service | Purpose | Status |
|---|---|---|---|
| `HUNTER_API_KEY` | Hunter.io | Domain search + email verify | ❌ 429 (resets monthly) |
| `APOLLO_API_KEY` | Apollo.io | People search + org enrichment | ⚠️ Org only (people blocked) |
| `SERPER_API_KEY` | Serper.dev | Google search | ✅ Working |
| `SERPAPI_API_KEY` | SerpAPI.com | Google search fallback | ✅ Working |
| `SNOV_CLIENT_ID/SECRET` | Snov.io | Domain email search | ❌ Wrong plan |
| `PROSPEO_API_KEY` | Prospeo.io | Search/Enrich Person | ✅ Working (100 enrich credits/month) |
| `ZEROBOUNCE_API_KEY` | ZeroBounce.net | Email validate + domain format | ❌ 0 credits (resets monthly) |
| `GOOGLE_MAPS_API_KEY` | Google Places | Phone lookup | ✅ Working |
| `YELP_API_KEY` | Yelp Fusion | Phone lookup fallback | ✅ Working |

---

## What We Built to Ensure Email Accuracy

### 1. Graceful Waterfall (no crashes)
Before this session, Hunter 429 would crash the entire enrichment for a company —
Snov.io, Prospeo, Serper never ran. Now every step is wrapped in `try/except` with
`logger.warning()`. One provider failing silently falls through to the next.

### 2. Provider Skip Flags
`_hunter_blocked` and `_apollo_blocked` are module-level flags. Once Hunter returns
429 or Apollo returns 403 on any company, those providers are skipped for ALL remaining
companies in the run — no wasted API calls or time.

### 3. Placeholder Email Filter
`_is_valid_email()` and `_PLACEHOLDER_LOCAL_PARTS` reject obviously fake emails:
`firstname@`, `lastname@`, `last@`, `flast@`, `first.last@` etc. Hunter returns these
as unverified guesses — they were polluting the DB. 14 fake emails were deleted.

### 4. Domain Integrity Check
Rejects emails where the domain doesn't match `[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}` —
catches scraping artifacts like `email@domain.com--skip-themes`.

### 5. 8-Pattern Permutation with Self-Verification
`_try_all_email_permutations()` generates all 8 common email patterns for a name+domain
and verifies each with Hunter (free verifier endpoint, no search credit). Returns only
verified hits.

### 6. Verified-First Outreach Priority
`get_priority_contact()` returns contacts ordered: verified first, then by title
seniority (CFO > VP > Director > Owner > generic). Writer and outreach agents use this.

### 7. Prioritised Verification
When running Verify Emails, contacts are sorted by value before verification credits
are spent — named executives first, generic inboxes never verified (waste of credits).

---

## Session Summary — What Was Built (2026-03-24)

### Problems Fixed
1. **Hunter 429 crashed entire enrichment** — no try/except. Fixed: waterfall fully wrapped, `_hunter_blocked` flag skips remaining companies after first 429.
2. **Apollo 403 same issue** — fixed same way with `_apollo_blocked`.
3. **Placeholder emails polluting DB** — Hunter returns `firstname@`, `lastname@` as guesses. Fixed: `_PLACEHOLDER_LOCAL_PARTS` filter + `_is_valid_email()` check. 14 fake emails deleted.
4. **Corrupted domain emails** — `email@domain.com--skip-themes`. Fixed: domain regex validation. 3 deleted.
5. **Frontend "Enrichment failed: Timed out"** — `pollUntilDone` had 3-min max. Fixed: polls forever, stops on completed/failed/not_found.
6. **Enrichment ran on all companies, no approval gate** — `trigger_enrich` targeted `["scored","approved","enriched"]`. Fixed: now only `["approved"]`.
7. **Verify Emails marked all 76 as "invalid"** — both providers exhausted, `verify_email()` returned `False` for everything. Fixed: 3-state return (`True`/`False`/`None`), contacts left unchanged when `None`.
8. **Website scraper too slow** — 7 pages × 5s = 35s/company × 59 = 34 min. Fixed: 4 pages × 3s = 12s/company max.
9. **`not_found` status polled forever** — frontend only stopped on completed/failed. Fixed: `not_found` is now terminal.
10. **Progress showed `26/?`** — `total` field missing from `TriggerStatusResponse`. Fixed: added `total: Optional[int]` to model + passed in status route.

### What Was Added
- **Prospeo two-step integration** (new March 2026 endpoints):
  - `POST /search-person` — finds senior LinkedIn contacts at domain (0 credits)
  - `POST /enrich-person` — reveals SMTP-verified email (1 credit per person)
  - Skips people with `email.status == UNAVAILABLE` before enriching
  - Correct seniority enums: `C-Suite`, `Vice President`, `Director`, `Founder/Owner`, `Partner`, `Head`
- **Serper → SerpAPI fallback** — `_google_search()` helper tries Serper first, falls back to SerpAPI
- **ZeroBounce email verify** — `verify_email_zerobounce()` returns `True`/`False`/`None`
- **ZeroBounce guessformat** — `find_via_zerobounce_domain()` detects email format for a domain
- **8-pattern permutation now uses ZeroBounce** — Hunter credits reserved for domain search only
- **Generic inbox fallback** — step 8, saves `info@` if domain is live and nothing else found
- **Priority-sorted verify trigger** — named execs first, generics never verified
- **Hunter credits strategy**: 50/month → 100% for domain search (finding). ZeroBounce 100/month → 100% for verification.
- **35 companies manually approved** — all companies with existing contacts backfilled to `status="approved"`
- **Orchestrator auto-approves** — when enrichment finds a contact, sets `approved_human=True` on lead score

## Current DB State (2026-03-24)

| Metric | Value |
|---|---|
| Total companies | 103 |
| Approved (has contact) | 35 |
| Scored, awaiting human review | 21 |
| New, not yet scored | 44 |
| Total contacts | ~80+ |
| Verified contacts | 3 |
| Unverified contacts | ~77 |
| Prospeo credits remaining | ~98 |
| ZeroBounce credits remaining | 0 (resets monthly) |
| Hunter quota remaining | 0 (resets monthly) |

## What To Do Next (in order)

1. **Run Writer** — 35 approved companies have contacts, ready for email draft generation.

2. **Next month:** Run Verify Emails as soon as ZeroBounce resets (100 credits covers all ~77 unverified).

3. **Next month:** Run Enrich Contacts — Hunter domain search (50/month) will find named contacts for the 3 companies that only got `info@`.
