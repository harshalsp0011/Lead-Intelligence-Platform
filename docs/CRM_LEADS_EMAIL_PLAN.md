# CRM Leads Email Flow — Feature Plan

> Created: April 2026
> Status: Planning — not yet implemented
> Scope: New tab on Email Review page + CRM-specific writer path + context storage

---

## What We Want to Achieve

The existing pipeline (Scout → Analyst → Writer) assumes every company was discovered
programmatically. It requires `company_features` (savings estimates, site count, deregulation)
and `lead_scores` (score_reason) before it can write an email.

CRM-sourced companies — those fetched from HubSpot with `data_origin = 'hubspot_crm'` — skip
Scout and Analyst entirely. They arrive in the `companies` table with basic fields only.
Running the standard writer on them fails silently (missing data = generic or blank drafts).

**The real scenario this solves:**
You met a prospect face-to-face. You know their situation — what they said, what they care about,
what came up in conversation. You added them to your CRM. Now you want to send a personalized
follow-up email. The context lives in your head, not in the database. This feature gives you a
place to write that context down, store it, and have the LLM draft the email from it — without
needing to run the full pipeline.

**Secondary goal:**
CRM leads are already qualified (you or your team put them in). They don't need a human approval
gate — the draft is pre-approved by default. The human still sees and can edit it before it sends,
but it skips the pending queue.

---

## The Gap (Why the Current System Breaks)

| Input Writer Needs | Pipeline Companies | CRM Companies |
|---|---|---|
| `company_features` (savings, site count, deregulated) | ✅ Written by Analyst | ❌ Missing |
| `lead_scores.score_reason` (why this is a good lead) | ✅ Written by Analyst | ❌ Missing |
| `contacts` (name, title, email) | ✅ Enriched by Analyst | ✅ Available (from CRM) |
| `email_win_rate` (angle hint) | ✅ Read by Writer | ✅ Available (if past emails sent) |
| Basic company info (name, industry, city, state) | ✅ | ✅ |

The writer currently returns `None` and logs a warning when `company` or `score` rows are missing.
CRM companies will always hit this path.

---

## What We Are Building

### 1. New DB Table — `company_context_notes`

Stores free-text meeting notes / personal context for any company.
Acts as the `score_reason` substitute for the CRM writer path.
Flagged as `source = 'manual_input'` so it is distinguishable from pipeline-derived data.

```
id             UUID PK
company_id     UUID FK → companies.id
notes          TEXT        ← the meeting context / discussion points
source         VARCHAR(50) default 'manual_input'
created_at     TIMESTAMP
created_by     VARCHAR(100)
```

### 2. New Backend Endpoints

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/companies/crm` | List all `data_origin = 'hubspot_crm'` companies with contacts + existing drafts + any saved context |
| `POST` | `/api/companies/{id}/context` | Save or update personal context notes for a company |
| `POST` | `/api/emails/crm-generate` | Generate a draft for a CRM company using stored context; saves as pre-approved |

### 3. CRM Writer — new function in `writer_agent.py`

`process_crm_company(company_id, context_notes, db_session)` — a parallel path to
`process_one_company()` that:

- Reads: company basic fields, contact, email_win_rate hint
- Uses `context_notes` as the `score_reason` field (replaces Analyst output)
- Constructs dummy savings range from industry average if features are missing
  (or omits the savings figure and lets the LLM focus on relationship angle instead)
- Runs the same Writer → Critic loop (context-aware generation + reflection)
- Saves draft with `approved_human = True` (pre-approved — CRM = trusted source)
- Still sets `low_confidence = True` if Critic never reaches 7.0

### 4. Frontend — Two Tabs on Email Review Page

`EmailReview.jsx` gets a tab switcher at the top.

**Tab 1 — Pipeline Queue** (unchanged)
Everything that exists today. No modifications.

**Tab 2 — CRM Leads**
- Fetches from `GET /api/companies/crm`
- Shows one card per CRM company with:
  - Company info (name, industry, city, state, site count if available)
  - Contact info (name, title, email from CRM)
  - Context notes text area — saves on blur or via explicit Save button
  - "Generate Email" button — calls `POST /api/emails/crm-generate`
  - Generated draft shown inline once created (subject + body)
  - Edit (inline) + Send buttons — Send calls the existing `PATCH /emails/{id}/approve`
- Badge: "CRM Lead" shown on each card
- If draft already exists for this company: shows it immediately (no need to regenerate)

---

## What Will Be Affected

| Layer | File / Table | Change |
|---|---|---|
| DB | new: `company_context_notes` table | New migration file |
| ORM | `database/orm_models.py` | Add `CompanyContextNote` model |
| Writer | `agents/writer/writer_agent.py` | Add `process_crm_company()` function |
| API models | `api/models/email.py` | Add `CrmGenerateRequest`, `CrmCompanyResponse` schemas |
| API routes | `api/routes/emails.py` | Add `POST /crm-generate` endpoint |
| API routes | `api/routes/leads.py` or new `api/routes/companies.py` | Add `GET /crm` + `POST /{id}/context` endpoints |
| API main | `api/main.py` | Register any new routers |
| Frontend | `dashboard/src/pages/EmailReview.jsx` | Add tab switcher + CrmLeadsTab component |
| Frontend | `dashboard/src/services/api.js` | Add 3 new API call functions |
| Docs | `docs/BUILD_STATUS.md` | Update phase completion table |

**What is NOT affected:**
- Existing pipeline writer (`process_one_company`) — untouched
- Tab 1 (Pipeline Queue) — untouched
- Outreach sender, follow-up scheduler, Tracker — untouched
- Scout, Analyst, Orchestrator — untouched

---

## Decisions (Locked)

| Question | Decision |
|---|---|
| Show all CRM companies or only unsent? | **All companies.** If a draft already exists (any status), show it immediately — don't regenerate. Show Regenerate button instead of Generate. |
| If company already has a draft, fetch and store it? | **Yes.** `GET /api/companies/crm` joins to `email_drafts` and returns the latest draft per company inline. No separate fetch needed. |
| Critic loop for CRM drafts? | **Yes, full loop kept.** Critic rubric extended with a 6th criterion: `context_accuracy` — does the email actually reflect the meeting discussion points? This replaces the pipeline's `score_reason` check. |
| Context notes editable after saving? | **Yes, always editable.** But raw notes are passed through an LLM formatter on save — the LLM structures them into clean bullet points before storing. The formatted version is what gets shown and used by the writer. |
| Missing savings data? | **Use industry average from `industry_benchmarks.json`.** Writer falls back to industry benchmark if `company_features` row is absent. |
| Context notes required before generating? | **Optional — warn inline if empty, but do not block generation.** |

---

## Updated Design Notes

### Context Formatter (added to Phase CRM-1)

When the user saves context notes, the raw text is not stored directly.
It is first sent to an LLM call that structures it into bullet points:

```
Raw input:
  "Met John at the conference, they have 12 locations across Ohio and Michigan,
   CFO mentioned they overpay on gas in winter, open to audit, no vendor contract currently"

Formatted output (stored):
  - Met contact (John) at conference
  - 12 locations across Ohio and Michigan
  - CFO noted overpayment on gas utilities in winter months
  - Currently has no vendor energy contract — open to switching
  - Expressed openness to a free audit
```

The writer uses the formatted bullet points as `score_reason`.
The raw input is also stored for reference (separate column) so nothing is lost.

### Extended Critic Rubric (6 criteria, 12 pts max, pass threshold stays at 7)

Added criterion for CRM drafts only:

| Criterion | Points | What it checks |
|---|---|---|
| personalization | 0–2 | Company name or specific detail mentioned |
| savings_figure | 0–2 | Dollar or % estimate present |
| clear_cta | 0–2 | Specific next step |
| human_tone | 0–2 | Reads like a person |
| subject_quality | 0–2 | Specific subject line |
| **context_accuracy** | **0–2** | **Email reflects the actual discussion points from context notes** |

Score is recalculated as sum of all 6 criteria (max 12). Pass threshold scales proportionally:
`pass = score >= 8.4` (7/10 × 12 = 8.4, rounds to 8).

The Critic prompt for CRM path receives the formatted context bullet points as an extra block
so it can check alignment.

---

## Phase Plan

### Phase CRM-0 — DB + ORM ✅
- [x] Write migration `database/migrations/019_create_company_context_notes.sql`
  - Columns: `id`, `company_id` (FK, CASCADE delete), `notes_raw` (TEXT), `notes_formatted` (TEXT),
    `source` (VARCHAR default `'manual_input'`), `created_at`, `updated_at`, `created_by`
  - Unique index on `company_id` — one context record per company (upsert target)
- [x] Add `CompanyContextNote` ORM model to `database/orm_models.py`
- [x] Run migration against DB, confirm table created — `CREATE TABLE` + `CREATE INDEX` ✅

### Phase CRM-1 — Backend: Context Endpoints + Formatter
- [ ] Add `GET /api/companies/crm` endpoint
  - Filter: `Company.data_origin == 'hubspot_crm'`
  - Returns per company: company fields + contact + latest draft (if any) + context notes (if any)
- [ ] Add `POST /api/companies/{id}/context` endpoint
  - Accepts: `{ notes_raw, created_by }`
  - Calls LLM formatter → produces `notes_formatted` (structured bullet points)
  - Upserts `company_context_notes` row (both `notes_raw` + `notes_formatted`)
  - Returns: `{ notes_raw, notes_formatted, updated_at }`
- [ ] Write LLM formatter function in `agents/writer/context_formatter.py`
  - System prompt: "Format these meeting notes into clean bullet points. Each point = one fact or signal. Keep it factual, no padding."
  - Input: raw notes string
  - Output: bullet-point string
  - Fallback: if LLM fails, store raw notes as-is in both columns

### Phase CRM-2 — CRM Writer + Extended Critic
- [ ] Extend `critic_agent.py` to accept an optional `context_notes` parameter
  - If provided: add `context_accuracy` criterion to rubric (6th criterion, 2 pts)
  - Adjust pass threshold to 8 (out of 12) when 6 criteria used
  - Recalculate score from all 6 criteria
  - Critic prompt includes context bullet points block for alignment check
  - If `context_notes` is None: uses original 5-criterion rubric unchanged (pipeline path unaffected)
- [ ] Add `process_crm_company(company_id, db_session)` in `writer_agent.py`
  - Load company basic fields + contact + `company_context_notes` (formatted)
  - Use win_rate hint via existing `get_best_angle()`
  - Use industry average from `industry_benchmarks.json` if no `company_features` row
  - Build writer context: `score_reason = notes_formatted` (or raw if formatted missing)
  - Call existing `_write_draft()` (no changes to writer prompt)
  - Call extended `critic_agent.evaluate(..., context_notes=notes_formatted)`
  - Run same rewrite loop (max 2 rewrites, `low_confidence` flag)
  - Save draft with `approved_human = True`
- [ ] Add `POST /api/emails/crm-generate` endpoint
  - Accepts: `{ company_id, created_by }`
  - Reads context from `company_context_notes` for this company
  - Calls `process_crm_company()`
  - Returns full draft response (same `EmailDraftResponse` schema)

### Phase CRM-3 — Frontend Tab
- [ ] Add tab switcher to `EmailReview.jsx`
  - Tabs: "Pipeline Queue" | "CRM Leads"
  - Default tab: Pipeline Queue
  - Tab state: `useState('pipeline')`
- [ ] Build `CrmLeadsTab` component (in `EmailReview.jsx` or separate file)
  - On mount: fetch `GET /api/companies/crm`
  - Renders one `CrmCompanyCard` per company
- [ ] Build `CrmCompanyCard` component
  - **Company info section**: name, industry, city/state, employee count, website
  - **Contact section**: name, title, email (from CRM)
  - **Context notes section**:
    - Text area (raw input) — pre-filled with `notes_raw` if already saved
    - "Save & Format" button → calls `POST /api/companies/{id}/context`
    - After save: shows formatted bullet points below the text area (read-only display)
    - Formatted notes always editable — clicking "Edit" re-opens text area
  - **Draft section**:
    - If draft exists (returned by API): show it immediately (subject + body)
    - If no draft: show "Generate Email" button (disabled if context not yet saved)
    - After generation: show draft inline with Edit + Send buttons
    - Regenerate button replaces Generate once draft exists
  - **Send button**: calls existing `approveEmail(draftId)` — no new endpoint needed
  - **Badge**: "CRM Lead" + "Pre-approved" shown on card header
- [ ] Add 4 new functions to `dashboard/src/services/api.js`:
  - `fetchCrmCompanies()`
  - `saveCompanyContext(companyId, notesRaw, createdBy)`
  - `generateCrmEmail(companyId, createdBy)`
  - `regenerateCrmEmail(draftId)` — reuses existing `regenerateEmail()` or wraps it

### Phase CRM-4 — Polish + Docs
- [ ] Edge cases:
  - Company has no contact → show editable "To Email" field on card; store in draft as override
  - Context notes empty + Generate clicked → show inline warning banner, do not block
  - `low_confidence = true` on saved draft → show "⚠ Low confidence" badge on card
  - LLM formatter fails → fall back silently, store raw as both columns, show note to user
- [ ] Update `docs/BUILD_STATUS.md` — move CRM email flow from "In Planning" to Phase Completion table
- [ ] Update `agents/writer/README.md` — document `process_crm_company()` and context formatter

---

## Why This Is Safe to Build

- The CRM writer path is entirely additive — it does not touch `process_one_company()`.
- Tab 1 is untouched — existing pending queue is not affected.
- `approved_human = True` on save means the draft bypasses the normal approval gate but
  the human still sees it in Tab 2 and clicks Send — it is not auto-sent without human action.
- The new `company_context_notes` table has no FK constraints on any existing flow.
