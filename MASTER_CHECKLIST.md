# Master Project Checklist
# Utility Lead Intelligence Platform — Agentic System

When every checkbox in this file is checked, the project is complete.
Check items off one by one as they are done.
Never remove a remaining item — mark it done instead.

---

## Agent Flow Reference

> **Note:** The flows below describe the current rule-based implementation.
> The agentic redesign (LLM reasoning layer) is documented in the "Agentic Intelligence Layer" section below.
> Each phase there states exactly what changes and how.

### Where does company data come from?

All company data originates from the **Scout agent**. The Analyst never discovers companies — it only scores companies Scout already saved.

**Scout → DB → Analyst** is the required order. You cannot run Analyst on a fresh DB.

---

### Scout Agent Flow

Scout is triggered with: `industry`, `location`, `count`

```
Scout trigger (POST /trigger/scout or full pipeline)
    │
    ▼
Phase 1: Configured directory sources (Yellow Pages etc. from DB)
    │   scrape HTML → extract fields → classify industry → deduplicate → save
    ▼
Phase 2: Tavily dynamic search
    │   Tavily finds directory URLs for that industry/location
    │   → scrape each directory → extract → classify → deduplicate → save
    ▼
Phase 3: Google Maps / Yelp API (ranked by past performance)
    │   returns structured results: name, address, category, phone, website
    ▼
For each company found:
    ├─ extract_all_fields(html, text) → name, city, state, phone, website
    ├─ classify_industry(category) → maps to: healthcare/hospitality/manufacturing/
    │                                          retail/public_sector/office/education/...
    ├─ normalize_state(raw) → two-letter code (e.g. "New York" → "NY")
    ├─ duplicate check (by website domain OR name+city)
    └─ save to companies table with status = 'new'
```

**What Scout saves per company (contract — same for ALL sources):**

| Field | Google Maps | Yelp | Directory/Tavily | Notes |
|---|---|---|---|---|
| `name` | ✅ from API | ✅ from API | ✅ scraped | Required — dropped if missing |
| `industry` | ✅ mapped from place type | ✅ mapped from category | ✅ classified | Required — dropped if unknown |
| `city` | ✅ parsed from address | ✅ from location.city | ✅ scraped | Optional |
| `state` | ✅ parsed from address (2-letter) | ✅ from location.state (2-letter) | ✅ extracted | Used for electricity rate |
| `website` | ✅ websiteUri | ❌ Yelp never returns it | ✅ scraped | Yelp limitation — by design |
| `employee_count` | ✅ crawled from website | ❌ no website to crawl | ✅ crawled | Yelp companies always NULL |
| `site_count` | ✅ crawled from website | ❌ no website to crawl | ✅ crawled | Yelp companies always NULL |
| `phone` | ✅ optional | ✅ optional | ✅ scraped | Optional |
| `status` | `'new'` | `'new'` | `'new'` | Analyst targets new/enriched |

**Crawl rule (all sources):** If `website` is present and `employee_count`/`site_count` are not already known, Scout crawls the website with requests+BeautifulSoup to extract those values before saving to DB. This ensures Analyst always has the best available data.

**Yelp limitation:** Yelp's API never returns a business website URL — only the Yelp listing page. So Yelp companies will always have `website=NULL`, `employee_count=NULL`, `site_count=NULL`. The Analyst handles this gracefully (defaults to 1 site, 0 employees, lower data quality score → lower tier).

**If a company has no website:** Scout still saves it. Only `name + industry + city` required.

---

### Analyst Agent Flow (Phase A — Agentic, current)

Analyst is triggered with: list of `company_ids` (status = `new` or `enriched`)

```
For each company_id:
    │
    ▼
Step 1: Load company from DB
    │   Gets: name, website, industry, state, employee_count, site_count
    │
    ▼
Step 2: Website crawl (conditional)
    │   IF website exists AND (site_count=0 OR employee_count=0):
    │       crawl with requests + BeautifulSoup
    │       → extracts location count + employee signals
    │
    ▼
Step 3: Apollo API fallback
    │   IF employee_count still 0 AND website exists:
    │       POST /api/v1/organizations/enrich → fills employee_count, state, city
    │
    ▼
Step 4: LLM Inspector  [agents/analyst/llm_inspector.py → inspect_company()]
    │   SKIPPED if: industry known AND employee_count>0 AND site_count>0
    │
    │   Input:  name, website, industry, employee_count, site_count, crawled_text
    │   Output: { inferred_industry, data_gaps, action, confidence }
    │
    │   → If inferred_industry set AND DB industry="unknown": update industry
    │   → If action="enrich_before_scoring": run re-enrichment loop (Step 4b)
    │
    ▼
Step 4b: Re-enrichment loop (only if LLM requested it, max 2 loops)
    │   → re-crawl website → re-call Apollo
    │   → stop early if employee_count found
    │   → log result to agent_run_logs
    │
    ▼
Step 5: Calculate utility spend  [spend_calculator.py — deterministic]
    │   Look up industry_benchmarks.json:
    │       avg_sqft_per_site × kwh_per_sqft × electricity_rate_by_state
    │   + telecom_per_employee × employee_count
    │   → total_spend ($/year)
    │   Unknown industry → falls back to 'default' benchmark (never crashes)
    │
    ▼
Step 6: Calculate savings potential  [savings_calculator.py — deterministic]
    │   total_spend × 8%  → savings_low
    │   total_spend × 15% → savings_mid   ← used for scoring
    │   total_spend × 24% → savings_high
    │
    ▼
Step 7: Data quality score (0–10)  [score_engine.assess_data_quality()]
    │   +2 pts each: has_website, has_locations_page, site_count>0,
    │                employee_count>0, contact_found
    │
    ▼
Step 8: Compute score (0–100)  [score_engine.compute_score() — deterministic]
    │   Score = (Recovery×0.40) + (Industry×0.25) + (Multisite×0.20) + (DataQuality×0.15)
    │   Tier: ≥70=high  ≥40=medium  <40=low
    │
    ▼
Step 9: LLM Score Narrator  [llm_inspector.generate_score_narrative()]
    │   Generates specific sentence from company context
    │   Falls back to rule-based template if LLM fails
    │   Example: "250-employee healthcare company, 3 sites in deregulated NY —
    │             strong audit candidate with ~$180k annual savings potential"
    │
    ▼
Step 10: Save to DB
    │   company_features row  → spend/savings/quality numbers
    │   lead_scores row       → score + tier + narrative reason + scored_at timestamp
    │   company.status        → 'scored'
    │   agent_run_logs row    → "healthcare | score=68 tier=medium | llm: inferred=healthcare action=score_now"
```

**What happens if data is missing:**

| Missing data | Phase A behaviour | Does it crash? |
|---|---|---|
| `industry = unknown` | LLM infers from name + website text | No |
| `employee_count = 0` + website exists | LLM triggers re-enrichment loop (max 2x) | No |
| `employee_count = 0` + no website | Scores with 0 — no enrichment possible | No |
| `site_count = 0` | Defaults to 1 in calculations | No |
| `state` missing | Uses national average electricity rate | No |
| LLM fails/times out | Falls back to rule-based silently | No |
| All data missing | Still scores — low tier, logged | No |

---

### Full Pipeline Order

```
Scout (finds companies, saves to DB with status='new')
    ↓
Analyst (scores companies, saves lead_scores, sets status='scored')
    ↓
Human approval (review scores on Leads page, approve/reject)
    ↓
Writer (drafts emails for approved high-tier companies)
    ↓
Outreach (sends approved email drafts)
```

Each stage is independent — you can trigger any stage alone via Triggers page.

---

## Phase 0 — Foundation (Database Schema)
Build the database tables that every agent and feature depends on.
Nothing agentic can work without this foundation.

### DB Migrations
- [x] `008_create_agent_runs.sql` — one row per pipeline run (chat or Airflow)
- [x] `009_create_agent_run_logs.sql` — step-by-step audit log inside each run
- [x] `010_create_source_performance.sql` — Scout learning memory (best source per industry/location)
- [x] `011_create_email_win_rate.sql` — Writer learning memory (best template per industry)
- [x] `012_create_human_approval_requests.sql` — human-in-loop queue + email notification tracking
- [x] `013_alter_companies_add_run_id.sql` — link companies to the run that found them + quality_score

### ORM Models
- [x] `AgentRun` model added to `orm_models.py`
- [x] `AgentRunLog` model added to `orm_models.py`
- [x] `SourcePerformance` model added to `orm_models.py`
- [x] `EmailWinRate` model added to `orm_models.py`
- [x] `HumanApprovalRequest` model added to `orm_models.py`
- [x] `Company` model updated with `run_id` and `quality_score` fields

---

## Phase 1 — Chat Agent + Scout Expansion + UI Visuals
Primary interface: user types in chat, agent executes the right task.
Scout finds more companies from more sources.
UI shows live visuals as things happen.

### 1A — Chat Agent Backend
- [x] `agents/chat_agent.py` — LangChain conversational agent with tool routing
- [x] Tools registered in chat agent:
  - [x] `search_companies(industry, location, count)` — triggers Scout
  - [x] `get_leads(tier, industry)` — queries DB for scored leads
  - [x] `get_outreach_history()` — fetches companies already emailed
  - [x] `get_replies()` — fetches received replies and their sentiment
  - [x] `run_full_pipeline(industry, location, count)` — triggers full run
  - [x] `approve_leads(company_ids)` — marks leads as human approved (Phase 2)
  - [ ] `approve_emails(draft_ids)` — marks drafts as human approved (Phase 3)
  - [ ] `draft_email(company_id)` — triggers Writer for one company (Phase 3)
- [x] Chat agent creates an `agent_runs` row at the start of every run
- [x] Chat agent updates `agent_run_logs` after each tool call
- [x] `POST /chat` API route added to `api/routes/chat.py`
- [x] Chat API returns both a text reply and structured data (companies, leads, replies)

### 1B — Scout Expansion (More Companies)
- [x] Scout reads `source_performance` table at run start to rank sources by `avg_quality_score`
- [x] Source priority order implemented:
  - [x] 1. PostgreSQL cached sources (directory scraper)
  - [x] 2. Tavily search fallback
  - [x] 3. Google Maps API (free tier)
  - [x] 4. Yelp Business Search (free tier)
- [x] Scout Critic added (`agents/scout/scout_critic.py`):
  - [x] Evaluates quality score 0–10 after each source (website 5pts, city 3pts, phone 2pts)
  - [x] Stops when target count reached OR all sources exhausted
  - [x] Phone/email missing handled gracefully — never fails on absent contact info
- [x] Duplicate check improved — domain normalization + name+city fallback (no more full table scan)
- [x] Scout writes `run_id` to `companies.run_id` for every company it saves
- [x] Scout updates `source_performance` table after every source attempt (upsert)
- [x] `agents/scout/google_maps_client.py` — Google Maps Places API integration
- [x] `agents/scout/yelp_client.py` — Yelp Business Search integration
- [x] `GOOGLE_MAPS_API_KEY` and `YELP_API_KEY` added to settings + .env.example
- [ ] API keys filled in `.env` (GOOGLE_MAPS_API_KEY, YELP_API_KEY) — needs user action

### 1C — UI: Chat Panel
- [x] Chat panel component added to React dashboard (`src/pages/Chat.jsx`)
- [x] Chat panel shows conversation history (user messages + agent responses)
- [x] Agent responses show structured data inline (company cards, lead cards, draft previews)
- [x] Chat panel accessible from all pages (sidebar nav → Chat Agent)
- [x] `src/services/api.js` updated with `sendChatMessage()` function

### 1D — UI: Scout Visual
- [x] Live company cards appear on screen as Scout finds them (3s polling)
- [x] Each card shows: company name, industry, city, source, quality score
- [x] Source indicator badge on each card (where it came from)
- [x] `src/pages/ScoutLive.jsx` — live Scout results page with trigger form

### 1E — UI: Pipeline Status Bar
- [x] Pipeline status bar component (`src/components/PipelineStatusBar.jsx`)
- [x] Shows current active stage: Scout → Analyst → Writer → Outreach → Tracker
- [x] Shows count at each stage (companies found, scored high/medium, drafts)
- [x] Embedded in ScoutLive page; reusable on any page
- [x] `dashboard/Dockerfile` updated to Vite multi-stage build (nginx serves dist/)
- [x] `GET /pipeline/run/{run_id}` endpoint added to pipeline.py

---

## Phase 2 — Analyst + Human-in-Loop (Leads Review)
Analyst scores companies. Pipeline pauses. Human reviews and approves before Writer runs.

### 2A — Analyst connects to run tracking
- [x] Analyst updates `agent_runs.current_stage` to `analyst_running` when it starts
- [x] Analyst updates `agent_runs.companies_scored` counter after scoring
- [x] Analyst logs each scoring action to `agent_run_logs`
- [x] Analyst updates `agent_runs.status` to `analyst_awaiting_approval` when done

### 2B — Human Approval: Leads
- [x] After Analyst finishes, system creates a `human_approval_requests` row (`approval_type = 'leads'`)
- [x] `agents/notifications/email_notifier.py` — sends approval email to reviewer
- [x] Approval email contains: list of scored companies, scores, link to review page
- [x] `POST /approvals/leads` API route — marks selected leads as approved, rejects others
- [x] On approval: `agent_runs.status` updates to `analyst_complete`, Writer starts
- [x] On rejection: run cancelled, `agent_runs.status` = `cancelled`
- [x] `human_approval_requests` row updated with `approved_by`, `approved_at`

### 2C — UI: Lead Review Page
- [x] Leads review page shows all scored companies (fixed field name mapping: company_id, score, site_count)
- [x] Each company shows: name, score, tier, savings estimate, industry, city
- [x] Checkboxes to select which companies to approve
- [x] "Approve Selected" button submits bulk approval
- [x] Inline "Approve" / "Reject" per row
- [x] `src/pages/Leads.jsx` — field names fixed to match API response schema

### 2D — Chat Agent: approve_leads tool
- [x] `approve_leads(company_ids)` tool added to chat agent
- [x] System prompt updated with approve_leads trigger phrase

---

## Phase 2.5 — Chat Resilience, Live Progress, UI Fixes & Chat Intelligence
Bugs fixed and reliability improvements after Phase 2 deployment.

### Chat Backend
- [x] `POST /chat` returns `run_id` immediately (background thread) — no more 30s browser timeout
- [x] `GET /chat/result/{run_id}` endpoint added — frontend polls for completion
- [x] `POST /chat/{run_id}/stop` endpoint added — marks run cancelled, frontend stops polling
- [x] `agents/chat_agent.py` — `run_chat()` accepts optional pre-generated `run_id`
- [x] Scout writes human-readable progress to `agent_run_logs` at every phase
- [x] `GET /pipeline/run/{run_id}` returns ALL logs (was capped at 5)

### Chat Agent: 3-Tier Routing
- [x] **Tier 1 — Conversational**: greetings/small talk → direct LLM reply, no tools
- [x] **Tier 2 — Intent pre-parser**: simple data queries (show leads, outreach history, replies) → Python extracts filters from message text, calls tool directly — LLM never guesses args
- [x] **Tier 3 — Agent loop**: complex/multi-step requests → full LangChain agent with tools
- [x] `_extract_lead_intent()` — extracts `tier` and `industry` from message without LLM
- [x] `_extract_outreach_intent()` — detects history vs replies queries
- [x] `get_leads` industry filter now case-insensitive (`func.lower()`)
- [x] Fix: LLM was adding `tier=high` to all lead queries — now Python sets args directly
- [x] System prompt updated with explicit `get_leads` arg examples to prevent hallucination

### Chat Frontend: Observability
- [x] Chat history persisted to `localStorage` — survives page refresh
- [x] Both user AND agent messages (including data cards) saved and restored
- [x] Active `run_id` persisted to `sessionStorage` — polling resumes if user navigates away mid-run
- [x] On remount: if `sessionStorage` has `chat_active_run_id`, polling resumes immediately
- [x] **Stop button** in progress indicator — stops polling immediately, shows step summary
- [x] On stop: detailed message shows every completed step + run ID + "check Leads page"
- [x] On server restart (404): same detailed step summary instead of generic error
- [x] **"View run logs"** expandable panel on every completed agent message — dark terminal showing full `AgentRunLog` from DB (status, companies found, scored, each step with agent/action/output)
- [x] `progressStepsRef` — steps stored in ref so async callbacks always see latest value (no stale closure)
- [x] Live `ProgressIndicator` replaces generic typing dots — shows `✓` / `→` step-by-step
- [x] "Clear history" button added to Chat header

### Leads Page Fixes
- [x] `GET /leads` 500 crash fixed — `_aware()` helper normalizes naive datetimes before sort
- [x] **N+1 query fix**: was 177 DB roundtrips for 59 companies (3 queries each) → now 4 bulk queries total
- [x] Load time: 9.2 seconds → 0.35 seconds
- [x] **Scroll fixed**: `min-h-screen` → `h-full overflow-y-auto` — page scrolls inside app shell
- [x] **Dynamic industry dropdown**: `GET /leads/industries` endpoint returns distinct DB values — no more hardcoded list
- [x] Industry filter auto-updates as new industries are scouted
- [x] Retry button added to error banner

### Triggers Page
- [x] `ActiveRunStatus` now shows real result summary (companies saved, tiers, drafts) when run completes
- [x] "View in Leads page →" button appears on completion
- [x] Industry field changed from `<select>` to `<input type="text" list="...">` + `<datalist>` — free-type with DB suggestions
- [x] Polls every 3s (was 5s)

### Scout Blocklist
- [x] `_UNSCRAPPABLE_DOMAINS` blocklist added to `search_client.py` (27 domains)
- [x] Sites that require login/paywall (glassdoor, zoominfo, seamless.ai, linkedin, etc.) skipped immediately
- [x] Scout reaches Google Maps/Yelp 60–90 seconds faster per run

---

## Agentic Intelligence Layer — Design Reference

This section defines the agentic redesign across all agents.
"Agentic" means the system **reasons, decides, acts, and evaluates** — not just executes fixed rules.

### What agentic means here

```
Automation (what we had):
  User → fixed code → fixed query → fixed formula → result

Agentic (what we are building):
  User → LLM reasons about intent
       → decides what tools to call + in what order
       → executes tools
       → evaluates result quality
       → loops if result is not good enough
       → returns result
```

**LLM = decision + reasoning layer only**
**APIs / DB / math = tools it calls (deterministic, never LLM)**

LLM never does math. LLM never calls external APIs directly.
LLM only: classifies, infers, decides, evaluates, generates text.

---

### Phase A — Agentic Analyst: LLM Reasoning Layer ✅ COMPLETE

#### What was there before (rule-based)
- Industry classification: exact string match only — `"healthcare"` → 90 pts; `"unknown"` → 45 pts penalty
- Data gaps: if `employee_count=0` → silently used 0, score penalized, never retried
- Score reason: hardcoded template — `"1-site healthcare organization. Estimated $45k in recoverable savings."`
- No feedback loop: bad data always produced a bad score

#### What was built
- [x] `agents/analyst/llm_inspector.py` — new file, two public functions:
  - [x] `inspect_company()` — LLM reads name + website + crawled text → infers industry, detects gaps, returns action
  - [x] `generate_score_narrative()` — LLM writes a specific one-sentence score reason from company context
  - [x] `_call_llm()` — handles Ollama and OpenAI transparently (provider from `.env`)
  - [x] `_fallback_narrative()` — rule-based fallback if LLM fails (identical to old template)
- [x] `agents/analyst/analyst_agent.py` updated:
  - [x] `gather_company_data()` — calls `inspect_company()` after initial enrichment
  - [x] Industry inference applied when DB value is `"unknown"` or empty
  - [x] Re-enrichment loop (max 2x) runs when LLM returns `action="enrich_before_scoring"`
  - [x] `_inspection_log` string carried through to `run()` for DB logging
  - [x] `process_one_company()` — replaces `score_engine.generate_score_reason()` with `generate_score_narrative()`
  - [x] `run()` — logs LLM inspector decision per company to `agent_run_logs` table
- [x] LLM skipped entirely when industry known AND `employee_count > 0` AND `site_count > 0`
- [x] Full fallback safety — any LLM failure falls back silently, scoring never blocked

#### How it works (actual implementation)
```
Load company from DB
        ↓
Step 1: Website crawl (if site_count=0 OR employee_count=0)
        ↓
Step 2: Apollo API fallback (if employee_count still 0 after crawl)
        ↓
Step 3: LLM Inspector  [SKIP if all data present]
  agents/analyst/llm_inspector.py → inspect_company()
  Input:  name, website, industry, employee_count, site_count, crawled_text
  Output: {
    "inferred_industry": "healthcare",    ← null if already known
    "data_gaps": ["employee_count"],
    "action": "enrich_before_scoring",   ← or "score_now"
    "confidence": "high"
  }
  → If inferred_industry set AND DB industry was "unknown": update enriched["industry"]
        ↓
Step 4: Re-enrichment loop (only if action="enrich_before_scoring")
  → re-crawl website
  → re-call Apollo
  → stop early if employee_count found
  → max 2 loops, logs result
        ↓
Step 5: score_engine.compute_score()  ← UNCHANGED deterministic math
  Score = (Recovery×0.40) + (Industry×0.25) + (Multisite×0.20) + (DataQuality×0.15)
        ↓
Step 6: LLM Score Narrator
  agents/analyst/llm_inspector.py → generate_score_narrative()
  Old output: "1-site healthcare organization. Estimated $45k in recoverable savings."
  New output: "250-employee healthcare company, 3 sites in deregulated NY —
               strong audit candidate with ~$180k annual savings potential"
        ↓
Step 7: Save to DB
  company_features row + lead_scores row (with scored_at timestamp)
  company.status = "scored"
  agent_run_logs: "healthcare company | score=68 tier=medium | llm: inferred=healthcare action=score_now"
```

#### Where results appear in UI
| Result | Where to see it |
|---|---|
| Inferred industry (was unknown → healthcare) | Leads page → Industry column |
| LLM score narrative | LeadDetail page → Score reason field |
| LLM inspector decision per company | Chat → "View run logs" panel after analyst run |
| All inspector logs | Docker logs: `[inspector] CompanyName — ...` |

#### Fallback behaviour
| Failure scenario | What happens |
|---|---|
| LLM returns bad JSON | `inspect_company()` catches exception → returns `action="score_now"`, no industry change |
| LLM times out | Same — silent fallback, warning logged |
| LLM narrator fails | `generate_score_narrative()` returns old template string via `_fallback_narrative()` |
| Ollama not running | Both functions catch the connection error and fall back |
| Re-enrichment finds nothing | Scores with whatever data is available, logs "exhausted" |

#### Token cost
| Scenario | LLM calls | Tokens |
|---|---|---|
| All data present (skip inspector) | 1 (narrator only) | ~80 |
| Industry unknown OR employee_count=0 | 2 (inspector + narrator) | ~180 |
| Re-enrichment triggered | 2 (inspector + narrator) | ~200 |
| LLM provider | Ollama (local) = $0 · GPT-4o-mini = ~$0.0003/company | |

---

### Phase B — Scout: Agentic Query Planning ✅ COMPLETE (2026-03-22)

#### What we had
- Fixed query: `"{industry} in {location}"` — one string per source
- No reasoning about what variants to try
- Deduplication: domain match OR name+city match (rule-based only)
- No quality check: if 5 companies found for target of 20, still stops

#### What was built

**New files:**
- `agents/scout/llm_query_planner.py` — `plan_queries()` + `plan_retry_queries()` + `_call_llm()` + `_fallback_queries()` + `_retry_fallback()`
- `agents/scout/llm_deduplicator.py` — `deduplicate()` + `_rule_dedup()` + `_find_suspicious_pairs()` + `_ask_llm_which_are_duplicates()`

**Updated files:**
- `agents/scout/scout_agent.py` — `run()` wires: query planner → multi-query API calls → LLM dedup → quality retry
- `agents/scout/google_maps_client.py` — `search_companies()` accepts `query_text` param
- `agents/scout/search_client.py` — added `search_with_queries()` for planned queries

#### How it works now
```
User: "find schools in Buffalo"
        ↓
LLM Query Planner (~80 tokens):
  Output: ["elementary schools Buffalo NY", "private schools Western New York",
           "K-12 school districts Erie County NY", "universities Buffalo NY"]
        ↓
Run ALL queries → Google Maps (separate Places API call per query) + Tavily
        ↓
LLM Deduplicator (~150 tokens):
  Pass 1: exact domain dedup (fast, handles ~80%)
  Pass 2: name-similar pairs (similarity ≥ 0.75) → LLM decides which are same company
  "Buffalo City School District" + "BCSD" → same, drop BCSD
        ↓
Quality Check:
  found=12, target=20 → plan_retry_queries() → 3 new queries → retry once
  found=17, target=20 → ≥ 80%, accept and save
        ↓
Save to DB, update source_performance
```

**Fallback:** any LLM failure → falls back to 3 static queries. Scout never blocked by LLM.

**LLM calls per Scout run:** up to 3 (~300 tokens). Free with Ollama.

**Checkboxes:**
- [x] `llm_query_planner.py` created with `plan_queries()` and `plan_retry_queries()`
- [x] `llm_deduplicator.py` created with domain dedup + LLM name-pair review
- [x] `scout_agent.py` updated — planner at start of `run()`, multi-query API loop
- [x] `google_maps_client.py` updated — accepts `query_text` param
- [x] `search_client.py` updated — added `search_with_queries()` function
- [x] Fallback on any LLM failure (static queries / domain-only dedup)
- [x] Quality check retry loop (< 80% of target → generate 3 more queries → retry once)
- [x] All decisions logged to `agent_run_logs` via `_log_progress()`

---

### Phase C — Writer + Critic Loop

#### What we have now
- Writer loads industry template, fills placeholders, calls LLM to polish body + generate subject
- No evaluation of output quality
- No retry — whatever LLM returns first is saved

#### What we will change
1. **Writer generates from context, not template** — LLM reads company data + score reason and writes the email reasoning about what angle will work best for this specific company
2. **Critic Agent** — separate LLM call evaluates the draft on a 0–10 rubric
3. **Rewrite loop** — if Critic scores < 7, Writer sees the feedback and rewrites. Max 2 loops.
4. **Confidence flag** — if after 2 rewrites still < 7, draft saved with `low_confidence = true`

#### How it will work
```
Approved company selected for outreach
        ↓
Writer Agent (~400 tokens):
  Input:  company name, industry, site_count, savings_mid, contact name, score_reason
  Reasons: "3-site healthcare company, deregulated state, $180k savings →
            I should lead with electricity cost angle and mention audit process"
  Output: full email draft (subject + body)
        ↓
Critic Agent (~250 tokens):
  Input:  the draft
  Evaluates:
    - Personalized to company? (not generic)
    - Mentions specific savings number?
    - Has clear ask / CTA?
    - Sounds human (not template)?
    - Subject line specific?
  Output: { "score": 6, "reason": "no specific savings figure mentioned",
            "instruction": "add the $180k annual savings estimate in paragraph 2" }
        ↓
If score < 7:
  Writer rewrites with Critic instruction → new draft
  Critic re-evaluates
  Max 2 loops
        ↓
If score >= 7 (any loop):
  Save draft → move to human review queue
        ↓
If still < 7 after 2 rewrites:
  Save draft with low_confidence=true → human review flags it
```

**LLM calls per email:** 2–6 (1 write + 1–2 critic + 0–2 rewrites). ~1,000 tokens. Cheap with Ollama.

---

### Phase D — Chat: Dynamic Filter Generation

#### What we have now
- 3-tier routing: conversational / intent pre-parser / agent loop
- Intent pre-parser uses Python string matching to extract `tier` and `industry`
- Tools have fixed schemas — always the same parameters

#### What we will change (small, already mostly agentic)
1. **LLM builds filter combinations dynamically** — "show me large schools that haven't been contacted" → LLM extracts `{industry: education, min_employees: 100, status: new}`
2. **Context carry-forward** — "now filter those to deregulated states only" → LLM adds to previous filter, doesn't start over

#### How it will work
```
User: "how many schools do we have right now?"
        ↓
LLM reasons:
  "schools" → industry = education
  "right now" → current DB state
  "how many" → count query
        ↓
Calls: get_leads(industry="education")
Returns: "You have 14 education companies — 3 high, 8 medium, 3 low tier"

User: "show me the ones in deregulated states only"
        ↓
LLM reasons: continue previous context + add state filter
Calls: get_leads(industry="education", deregulated_only=True)
```

---

### Agentic Architecture Summary

```
┌─────────────────────────────────────────────────────────────┐
│                LLM REASONING LAYER                          │
│  Scout: query planning, deduplication, quality check        │
│  Analyst: industry inference, data gap detection, narration │
│  Writer: context-driven draft generation                    │
│  Critic: quality evaluation + rewrite instruction           │
│  Chat: dynamic filter extraction, context carry-forward     │
└──────────────────────────┬──────────────────────────────────┘
                           │ decides what to call
┌──────────────────────────▼──────────────────────────────────┐
│                TOOLS LAYER (deterministic)                  │
│  Google Maps API  ·  Yelp API  ·  Tavily API               │
│  Apollo/Hunter    ·  Website crawler                        │
│  Spend calculator ·  Score formula (math only)              │
│  DB queries       ·  Email sender                           │
└─────────────────────────────────────────────────────────────┘
```

**Token cost per full pipeline run (Ollama = $0, GPT-4o-mini ≈ $0.005):**

| Phase | LLM calls | Tokens |
|---|---|---|
| Scout query planning | 3 | ~300 |
| Analyst per company (×20) | 2×20 | ~3,600 |
| Writer + Critic per email (×5) | 4×5 | ~5,000 |
| Chat per message | 1 | ~200 |
| **Total per run** | | **~9,100** |

---

### Build Order

```
Step 1 → Phase A: Analyst LLM reasoning layer           ✅ DONE (2026-03-22)
         (industry inference + data gap loop + score narration)

Step 2 → Phase B: Scout agentic query planning           ✅ DONE (2026-03-22)
         (query expansion + multi-query API calls + LLM dedup + quality retry)

Step 3 → Phase C: Writer + Critic loop                   🔄 IN PROGRESS (2026-03-22)
         (context-driven generation + quality evaluation + rewrite loop)
         Reference: docs/PHASE_C_WRITER_CRITIC.md
         Remaining: 3C win-rate learning, 3C run tracking, 3D approval email, 3D Approve All

Step 4 → Phase D: Chat dynamic filters                   🔲 PLANNED
         (already mostly done — small enhancement)
```

---

## Phase 2.6 — Contact Enrichment Hardening ✅ COMPLETE (2026-03-24)

### Waterfall Reliability
- [x] All 8 waterfall steps wrapped in `try/except` — one provider failing never crashes others
- [x] `_hunter_blocked` flag — skips Hunter for rest of run after first 429
- [x] `_apollo_blocked` flag — skips Apollo for rest of run after first 403
- [x] Website scraper: pages reduced 7→4, timeout reduced 5s→3s (was causing 34-min runs)

### Email Quality Gates
- [x] `_PLACEHOLDER_LOCAL_PARTS` filter — rejects `firstname@`, `lastname@`, `flast@` etc.
- [x] Domain integrity check — rejects emails with corrupted domains (`domain.com--skip-themes`)
- [x] 14 placeholder + 3 corrupted emails deleted from DB

### New Providers Added
- [x] **Prospeo** (new March 2026 endpoints) — `POST /search-person` + `POST /enrich-person`; correct seniority enums; skips UNAVAILABLE; enriches top 2 per company; SMTP-verified results
- [x] **Serper → SerpAPI fallback** — `_google_search()` helper, tries Serper first
- [x] **ZeroBounce validate** — `verify_email_zerobounce()` returns `True`/`False`/`None`
- [x] **ZeroBounce guessformat** — `find_via_zerobounce_domain()` detects email format + permutation
- [x] **Generic inbox fallback** — step 8, saves `info@` as last resort

### Credit Strategy
- [x] Hunter 50/month → 100% for domain search (finding), never for verification
- [x] ZeroBounce 100/month → 100% for verification only
- [x] 8-pattern permutation switched from Hunter verifier to ZeroBounce
- [x] `verify_email()` now returns `bool | None` — `None` = quota exhausted, contacts left unchanged

### Approval Gate
- [x] `trigger_enrich` now targets only `status="approved"` companies
- [x] Orchestrator auto-approves company when enrichment finds a contact (`approved_human=True`)
- [x] 35 companies with existing contacts manually backfilled to `approved`

### Frontend
- [x] `pollUntilDone` stops on `not_found` (container restart) — shows "Server restarted — run again"
- [x] `EnrichActiveStatus` stops on `not_found`
- [x] `TriggerStatusResponse` now includes `total` field — progress shows `26/59` not `26/?`
- [x] Verify Emails result shows `⚠ No credits` message when both providers exhausted

---

## Phase 3 — Agentic Writer + Critic Loop + Human-in-Loop (Email Review)
Writer generates context-driven emails. Critic evaluates and triggers rewrites. Human reviews before Outreach sends.

### 3A — Agentic Writer: Context-Driven Generation (replaces template fill)
- [x] Writer reads: company name, industry, site_count, savings_mid, contact name, score_reason, state
- [x] LLM reasons about which angle to take (cost savings / audit process / risk reduction) based on company profile
- [x] LLM generates full email (subject + body) — not template substitution
- [x] `agents/writer/llm_connector.py` updated to pass full company context, not template slots
- [x] `agents/writer/writer_agent.py` updated to call context-driven generator

### 3B — Critic Agent: Quality Evaluation Loop
- [x] Critic evaluates each draft on 0–10 rubric (separate LLM call):
  - [x] Personalized to this specific company (not generic)
  - [x] Mentions specific savings number
  - [x] Has clear CTA (call to action)
  - [x] Subject line specific (not "reduce your costs")
  - [x] Sounds human (not template-like)
- [x] Critic returns: `{ score, reason, rewrite_instruction }`
- [x] If score < 7: Writer rewrites using Critic instruction → re-evaluate
- [x] Max 2 rewrite loops per draft
- [x] If still < 7 after 2 rewrites: save with `low_confidence = true`
- [x] All rewrite attempts + scores logged to `agent_run_logs`
- [x] `agents/writer/critic_agent.py` — new file, Critic LLM call

### 3C — Writer reads email_win_rate (learning layer) ✅ COMPLETE (2026-03-24)
- [x] Before generating, Writer queries `email_win_rate` for best-performing angle per industry
- [x] If no history (cold start): LLM picks angle freely
- [x] If history exists (≥5 emails sent): LLM is told which angle has highest reply rate via `WIN RATE HINT` in prompt
- [x] LLM outputs `ANGLE:` field — one of 5 named angles (cost_savings, audit_offer, risk_reduction, multi_site_savings, deregulation_opportunity)
- [x] Angle saved as `template_used` in `email_drafts` — feeds `email_win_rate` when Tracker records reply events
- [x] `get_best_angle(industry, db)` function in `writer_agent.py`

### 3C — Writer connects to run tracking ✅ COMPLETE (2026-03-24)
- [x] `orchestrator.run_writer()` creates `AgentRun` row with `status="writer_running"`, `current_stage="writer_running"`
- [x] `run_id` passed through `task_manager` → `writer_agent.run(run_id=...)`
- [x] Writer increments `agent_runs.drafts_created` after each draft (live counter)
- [x] Orchestrator sets `status="writer_awaiting_approval"`, `current_stage="writer_complete"` when done

### 3D — Human Approval: Emails (SMTP Send on Approval)
- [x] `api/routes/emails.py` `approve_draft` endpoint wires SMTP send on approval
- [x] On approval: calls `email_sender.send_email()` → sets `company.status = "contacted"` → logs `outreach_event`
- [x] Response includes `sent: bool` and `message_id` so UI knows if send succeeded
- [x] After Writer finishes, `orchestrator.run_writer()` creates `human_approval_requests` row (`approval_type = "emails"`)
- [x] Approval notification email sent: table of drafts (company, contact, subject, angle, AI score) + "Review & Approve Drafts →" button
- [x] Email says "No emails have been sent yet" — reviewer knows nothing went out
- [x] Reject behavior: draft deleted, company `approved_human` stays `True` → Regenerate button or re-run Writer picks it up
- [ ] `human_approval_requests` row status updated when all drafts are acted on (deferred — requires batch tracking)

### 3E — UI: Email Review Page
- [x] Email review page shows all drafts for current run
- [x] Each draft shows: subject, body preview, company name, contact name
- [x] Inline edit for subject line and body
- [x] "Approve" / "Reject" per draft
- [x] `CriticBadge` component — shows AI score (green ≥7, amber <7) with rewrite count
- [x] `low_confidence` red warning banner on drafts that failed both rewrite attempts
- [x] "✓ Approve & Send" button — triggers immediate SMTP send (not just mark approved)
- [x] `api/models/email.py` — `EmailDraftResponse` now includes `critic_score`, `low_confidence`, `rewrite_count`
- [ ] "Approve All" bulk action

---

## Phase 4 — Outreach + Tracker + Auto Notifications
Outreach sends approved emails. Tracker monitors replies. Email alerts sent automatically.

### 4A — Remove Slack, Add Email Notifications
- [x] `agents/tracker/alert_sender.py` — Slack removed, email only
- [x] `agents/orchestrator/orchestrator.py` — Slack removed
- [x] `agents/orchestrator/task_manager.py` — Slack removed
- [x] `agents/orchestrator/pipeline_monitor.py` — Slack removed
- [x] `agents/tracker/tracker_agent.py` — Slack removed
- [x] All DAG files — Slack removed
- [x] `config/settings.py` — SLACK_WEBHOOK_URL removed
- [x] `.env` and `.env.example` — SLACK_WEBHOOK_URL removed
- [ ] `agents/notifications/email_notifier.py` — handles all notification types:
  - [ ] Reply received (auto, no human trigger)
  - [ ] Pipeline run completed summary
  - [ ] Approval needed (leads / emails)
  - [ ] Scout found 0 results (failure alert)
  - [ ] Daily pipeline status summary
- [ ] All Slack references removed from entire codebase
- [ ] `.env` — `SLACK_WEBHOOK_URL` removed, `ALERT_EMAIL` made required

### 4B — Outreach connects to run tracking
- [ ] Outreach updates `agent_runs.current_stage` to `outreach_running`
- [ ] Outreach updates `agent_runs.emails_sent` counter after each send
- [ ] Outreach updates `agent_runs.status` to `outreach_complete` when queue is done
- [ ] Each send logged to `agent_run_logs`

### 4C — Tracker: Always-on background process
- [ ] Tracker runs as persistent background service (not only on-demand)
- [ ] Tracker polls for new reply/open webhook events continuously
- [ ] On reply detected:
  - [ ] Classifies reply sentiment (positive / neutral / negative / unsubscribe)
  - [ ] Updates `outreach_events` row
  - [ ] Updates `companies.status`
  - [ ] Sends email alert automatically (no human trigger needed)
  - [ ] Updates `email_win_rate` table for the template+industry that got the reply
- [ ] On open detected:
  - [ ] Updates `outreach_events`
  - [ ] Updates `email_win_rate.emails_opened`
- [ ] Stuck lead detection still runs daily (5+ days without update)

### 4D — UI: Notification Center
- [ ] Notification center component in dashboard (`src/components/NotificationCenter.jsx`)
- [ ] Shows recent alerts: replies received, approvals needed, run failures
- [ ] Badge count on nav icon when unread notifications exist
- [ ] Clicking a notification navigates to the relevant page

### 4E — UI: Reply Inbox
- [ ] Reply inbox page (`src/pages/Replies.jsx`)
- [ ] Shows all received replies with: company, contact, reply text, sentiment, date
- [ ] Filter by sentiment (positive / neutral / negative)
- [ ] Link to full company profile per reply

### 4F — UI: Company Timeline
- [ ] Company detail page shows full outreach event timeline
- [ ] Events: discovered → scored → approved → emailed → opened → replied
- [ ] `src/pages/LeadDetail.jsx` updated with timeline section

---

## Phase 5 — Airflow Scheduled Runs with Human-in-Loop
Airflow runs the full pipeline on a schedule with pauses for human approval at key steps.

### 5A — Airflow DAG Update
- [ ] `dags/` — main pipeline DAG updated with approval pause points
- [ ] DAG step order:
  1. [ ] Scout task runs
  2. [ ] DAG pauses — sends approval email for leads
  3. [ ] DAG polls `human_approval_requests` status (checks every 15 min, times out at 24hr)
  4. [ ] On approval: Analyst task runs
  5. [ ] Writer task runs
  6. [ ] DAG pauses — sends approval email for drafts
  7. [ ] DAG polls approval status
  8. [ ] On approval: Outreach task runs
  9. [ ] Tracker confirmation task runs
- [ ] DAG creates `agent_runs` row with `trigger_source = 'airflow'`
- [ ] DAG updates `agent_runs.status` at each step transition
- [ ] DAG sends failure alert email if any task fails

### 5B — Airflow Schedule Config
- [ ] `.env` — `AIRFLOW_SCHEDULE` variable (default: weekly Monday 9am)
- [ ] `SCOUT_TARGET_INDUSTRIES` and `SCOUT_TARGET_LOCATIONS` used by scheduled DAG
- [ ] Airflow admin/password configurable via `.env`

---

## Phase 6 — Learning Activation
Agent decisions improve automatically based on past run data.

### 6A — Scout learns from source_performance
- [ ] Scout reads `source_performance` at run start and sorts sources by `avg_quality_score DESC`
- [ ] If no history for context: uses default priority order
- [ ] After each run: upserts `source_performance` with new quality score (rolling average)
- [ ] Verified: after 3 runs, Scout tries the best source first automatically

### 6B — Writer learns from email_win_rate
- [ ] Writer reads `email_win_rate` for target industry before picking template
- [ ] Picks template with highest `reply_rate` (minimum 5 sends required to count)
- [ ] After each reply/open event: Tracker updates `email_win_rate` counters and recalculates rates
- [ ] Verified: after 3 email cycles, Writer picks better templates automatically

### 6C — Learning visibility in UI
- [ ] `src/pages/Reports.jsx` updated with learning insights section:
  - [ ] Source performance table (source, industry, location, avg quality, total leads)
  - [ ] Email win rate table (template, industry, open rate, reply rate)

---

## Phase 7 — Full System Test
End-to-end verification that everything works together.

### 7A — Chat-triggered run test
- [ ] User types: "find 10 healthcare companies in Buffalo NY"
- [ ] Scout runs, companies appear live in UI
- [ ] Analyst scores them, approval email sent
- [ ] User approves leads via dashboard
- [ ] Writer drafts emails, approval email sent
- [ ] User approves drafts via dashboard
- [ ] Outreach sends emails
- [ ] Tracker detects simulated reply, auto email alert sent
- [ ] `agent_runs` row shows full lifecycle from `started` to `completed`
- [ ] `agent_run_logs` shows every step with no gaps

### 7B — Airflow-scheduled run test
- [ ] Airflow DAG triggered manually to simulate scheduled run
- [ ] DAG pauses after Scout, approval email received
- [ ] Approval submitted, DAG resumes
- [ ] DAG pauses after Writer, approval email received
- [ ] Approval submitted, Outreach sends
- [ ] Run completes, summary email sent
- [ ] `agent_runs.trigger_source = 'airflow'` confirmed

### 7C — Learning tables verified
- [ ] `source_performance` has data after Phase 7A test
- [ ] `email_win_rate` has data after Phase 7A test
- [ ] Second chat-triggered run picks sources in different order based on learning

### 7D — Final checks
- [ ] No Slack calls anywhere in codebase
- [ ] All email notifications deliver correctly
- [ ] All human-in-loop pauses work in both chat and Airflow flows
- [ ] Docker Compose starts all services cleanly
- [ ] API `/health` endpoint returns healthy
- [ ] All existing migrations run in order without errors (001 through 013)

---

## Summary

| Phase | Focus | Status |
|---|---|---|
| 0 | Database foundation | ✅ Complete |
| 1 | Chat agent + Scout expansion + UI visuals | ✅ Complete |
| 2 | Analyst + human-in-loop leads review | ✅ Complete |
| 2.5 | Chat resilience + live progress + UI fixes + chat intelligence | ✅ Complete |
| **A** | **Agentic Analyst: LLM industry inference + data gap loop + score narration** | ✅ Complete |
| **B** | **Agentic Scout: LLM query planning + deduplication + quality loop** | ✅ Complete |
| **B+** | **Scout enhancements: intent signals, news scout, save-count fix, location filter** | ✅ Complete |
| **Chat** | **LLM intent extraction + history context + confidence gating + observe→ask→act** | ✅ Complete |
| **C** | **Agentic Writer + Critic loop + SMTP send + human-in-loop email** | ✅ Complete |
| **C-fix** | **UI fixes: LeadDetail fields, Leads page approve, pending analysis, enrichment trigger** | ✅ Complete |
| **C+** | **SerpAPI news/press release source + signal scoring boost in Analyst** | 🔲 Planned |
| 4 | Outreach + Tracker + auto email notifications | 🔲 Not started |
| 5 | Airflow scheduled runs with approval pauses | 🔲 Not started |
| 6 | Learning activation (source + template selection) | 🔲 Not started |
| 7 | Full system test | 🔲 Not started |

---

## Current State (as of 2026-03-22 — Session 4)

**Running services:**
- Frontend: http://localhost:3000 (React via nginx)
- API: http://localhost:8001 (FastAPI + Uvicorn)
- Database: PostgreSQL on AWS RDS (Heroku Postgres)
- LLM: llama3.2 via Ollama at host.docker.internal:11434 (host Mac)

**Reference docs:**
- `docs/CHATBOT_ARCHITECTURE.md` — full chat system, memory, context, agentic concepts
- `docs/SCOUT_SOURCES_AND_SIGNALS.md` — all discovery sources, intent signals, dedup layers
- `docs/PHASE_C_WRITER_CRITIC.md` — Phase C design, execution flow, testing plan

---

**What works right now:**

| Feature | Status |
|---|---|
| Chat → Scout → find companies | ✅ Working |
| Chat: LLM intent extraction (replaces all keyword routing) | ✅ Working |
| Chat: conversation history passthrough (last 6 messages) | ✅ Working |
| Chat: confidence-gated routing (low confidence → asks user) | ✅ Working |
| Chat: Observe→Ask→Act (asks for location/industry before searching) | ✅ Working |
| Chat: score_reason shown per lead in LeadCard | ✅ Working |
| Chat: direct tool dispatch (no agent loop hallucination) | ✅ Working |
| Chat: stop button + step-by-step summary | ✅ Working |
| Chat: view run logs panel | ✅ Working |
| Chat history persists across refresh | ✅ Working |
| Leads page | ✅ Working |
| Triggers page | ✅ Working |
| Scout: Google Maps + Yelp + Tavily directory | ✅ Working |
| Scout: LLM query planner (4 diverse queries) | ✅ Working |
| Scout: LLM deduplicator (domain + name similarity) | ✅ Working |
| Scout: location-aware directory filter (skips Buffalo sources for Rochester) | ✅ Working |
| Scout: save-count fix (respects count limit, no more saving 44 when asked for 10) | ✅ Working |
| Scout: news scout Phase 0 (Tavily topic=news + LLM extraction) | ✅ Working |
| Scout: intent_signal stored on companies with buying signals | ✅ Working |
| Analyst: scoring + lead tiers + scored_at | ✅ Working |
| Analyst: LLM score_reason narrative | ✅ Working |
| Approve/reject leads | ✅ Working |
| Full pipeline: Scout → Analyst → Writer | ✅ Working |
| Email drafting + review page | ✅ Working |
| Email review: Critic score badge + low_confidence warning | ✅ Working |
| Email approval: triggers immediate SMTP send | ✅ Working |
| Enrichment bulk trigger: "👤 Enrich Contacts" button in Pipeline page | ✅ Working |
| Enrichment per-company: "👤 Find Contacts" button in LeadDetail page | ✅ Working |
| LeadDetail: Financial Estimates panel (utility/telecom spend, savings range) | ✅ Working |
| LeadDetail: Score Factors panel (Recovery Potential, Industry Fit, Multi-site, Data Quality) | ✅ Working |
| Leads page: Approve button visible for all unscored+unapproved leads (not just high tier) | ✅ Working |
| Leads page: Pending Analysis banner — companies with status=new shown as "awaiting analysis" | ✅ Working |
| Leads page: /leads/:companyId route registered (was missing, caused blank page) | ✅ Working |
| API: LeadResponse includes estimated_annual_utility_spend, telecom_spend, industry_fit_score, data_quality_score, multi_site_confirmed | ✅ Working |
| API: LeadListResponse includes pending_analysis_count | ✅ Working |
| Enrichment: website scraper fallback (BeautifulSoup mailto: + body email extract, /contact /about /team pages) | ✅ Working |
| Enrichment: waterfall chain — Hunter → Apollo → website scraper, stops at first hit | ✅ Working |
| Enrichment: contact_found + status='enriched' set on company after contacts saved | ✅ Working |
| Enrichment: Pipeline page polls trigger status, shows result banner (X contacts found / failed) | ✅ Working |
| Contact strategy: phone column added to companies table (migration 016) | ✅ Working |
| Contact strategy: Scout saves phone when found from Google Maps / Yelp / directories | ✅ Working |
| Contact strategy: phone shown in Leads table (clickable tel: link) + LeadDetail header | ✅ Working |
| Contact strategy: phone + city + website included in CSV export | ✅ Working |
| API: LeadResponse includes city, phone, website fields | ✅ Working |

---

### Contact Strategy — Why Only 2/59 Companies Got Contacts (2026-03-23)

Hunter free plan (50 searches/month) and Apollo people-search (paid-only) have almost no data
for small local SMBs (healthcare staffing, manufacturing shops, medical offices in Buffalo/Rochester).

**Waterfall enrichment order (implemented):**
1. Hunter domain-search — works for mid-large companies with public email patterns
2. Apollo people-search — requires paid plan ($49/mo), currently 403s on free tier
3. Website scraper (free) — fetches /contact, /about, /team pages, extracts mailto: links

**Enrichment steps completed:**
- Step 1: Phone column + website scraper + backfill trigger (✅ 2026-03-23)
- Step 2: Email pattern inference — detect pattern from scraped emails (tdepew@ → first_initial+lastname), find exec name on contact page, guess email, verify with Hunter verifier (✅ 2026-03-23)
  - `_detect_email_pattern()` — detects first_initial_lastname / firstname.lastname / firstname_lastname
  - `_apply_pattern()` — generates guessed email from name + pattern + domain
  - `verify_email_hunter()` — Hunter email verifier endpoint (free, 100/month, no search credit used)
  - `_guess_executive_email()` — finds exec name on contact/about pages via regex, generates + verifies guess
  - `scrape_phone_from_website()` — extracts phone from tel: links + regex on homepage
  - `/trigger/backfill-phones` — one-time endpoint to fill phones for all 69 companies with websites
  - Pipeline page: "📞 Backfill Phones" button with polling result banner

**Next enrichment steps (planned):**
- Step 3: SerpAPI name search — Google "{company} owner OR CFO OR president" to find the decision-maker name, apply pattern
- Step 4: LinkedIn company URL — constructed from name, shown in UI for manual lookup

**Best outreach for SMBs:**
- Phone call list (already implemented) — small local businesses answer phones; phone numbers from Scout (Yellow Pages, Google Maps)
- Website email scraper — works where businesses list emails on contact pages
- Manual entry via "Add Contact" button in LeadDetail for high-value targets

---

**Agentic system — current state:**

| Agent | Agentic capabilities | Status |
|---|---|---|
| **Scout** | LLM query planner · multi-variant API calls · LLM dedup · quality retry · news intent signals | ✅ Live |
| **Analyst** | LLM industry inference · data gap detection · re-enrichment loop · score narration | ✅ Live |
| **Writer** | Context-driven generation · Critic loop (rewrite up to 2x) · low_confidence flag · SMTP send on approval | ✅ Live |
| **Enrichment** | Tool use: Hunter → Apollo → website scraper (waterfall) · domain guard · name-only Apollo fallback · skip generic emails · bulk + per-company trigger · result polling banner | ✅ Live |
| **Chat** | LLM intent extraction · history context · confidence gating · observe→ask→act | ✅ Live |

---

**Next to build:**

**Phase C+ — SerpAPI Intent Source** (`docs/SCOUT_SOURCES_AND_SIGNALS.md`)
1. `agents/scout/serp_client.py` — Google News + press release search
2. Signal scoring boost in `agents/analyst/scoring_engine.py`
3. "Hot Lead" badge in `dashboard/src/pages/Leads.jsx`
