# Agentic Transformation Plan

> **Note:** This was the original planning doc. For the current built state, see
> `docs/AGENTIC_DESIGN.md`. Phases 0–3 and 2.6 are complete.

## 1. Vision

Build an agentic lead-generation platform where agents **reason, decide, act, and evaluate**
— not just execute fixed automation steps.

```
Automation (what we had):
  User → fixed code → fixed query → fixed formula → result

Agentic (what we are building):
  User → LLM reasons about intent
       → decides which tools to call and in what order
       → executes tools (APIs, DB, math — deterministic)
       → evaluates result quality
       → loops if result is not good enough
       → returns result
```

**LLM = decision and reasoning layer only.**
**Tools = deterministic execution (APIs, DB queries, math formulas).**

---

## 2. What "Agentic" Means Here

Agentic behaviors we are building:

| Behavior | Example |
|---|---|
| **Dynamic query planning** | "find schools" → LLM generates 5 search variants, not one hardcoded string |
| **Data gap detection** | Analyst notices employee_count=0 → decides to re-enrich before scoring |
| **Industry inference** | Company name "Buffalo Surgical" → LLM classifies as "healthcare" without exact match |
| **Output evaluation** | Writer Critic scores draft 0–10, triggers rewrite if quality is low |
| **Retry with feedback** | Writer sees Critic's reason → rewrites with targeted instruction |
| **Quality loops** | Scout checks if enough results found → generates more queries if not |
| **Context carry-forward** | Chat: "show me healthcare leads" → "filter to deregulated states" → LLM adds filter without restarting |

NOT agentic (stays rule-based — intentionally):
- Math calculations (spend, savings, scores) — LLM would hallucinate numbers
- DB queries — deterministic SQL
- Email sending — no reasoning needed
- Score threshold comparisons — business rules

---

## 3. Technology Stack

Primary approach: **LLM reasoning layer on top of existing deterministic tools**

| Layer | Technology | Role |
|---|---|---|
| LLM provider (default) | Ollama + llama3.2 (local) | Zero cost, runs on host Mac |
| LLM provider (optional) | OpenAI GPT-4o-mini | ~$0.005/run, cloud fallback |
| LLM framework | LangChain | Tool calling, prompt management |
| Chat agent | LangChain ReAct | Already live — conversational interface |
| API | FastAPI | Trigger endpoints, background tasks |
| Database | PostgreSQL (AWS RDS) | Business data + agent memory |
| Scheduler | Airflow (Phase 5) | Scheduled runs — add-on, not required |

**Note on LangGraph:** LangGraph was considered for orchestrating state machines between agents.
Decision: not used in current phases. The LLM reasoning layer achieves agentic behavior without
a full graph framework. LangGraph may be adopted in Phase 5+ if cross-agent state sharing becomes complex.

---

## 4. Agentic Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                LLM REASONING LAYER                          │
│                                                             │
│  Scout:    query planning · deduplication · quality check   │
│  Analyst:  industry inference · data gap detection          │
│            re-enrichment decision · score narration         │
│  Writer:   context-driven generation (best angle for co.)   │
│  Critic:   quality evaluation · rewrite instruction         │
│  Chat:     dynamic filter building · context carry-forward  │
└──────────────────────────┬──────────────────────────────────┘
                           │ decides what to call
┌──────────────────────────▼──────────────────────────────────┐
│                TOOLS LAYER (deterministic)                  │
│                                                             │
│  Google Maps API  ·  Yelp API  ·  Tavily search             │
│  Apollo org enrichment  ·  Hunter contact finder            │
│  Website crawler (requests + BeautifulSoup)                 │
│  Spend calculator  ·  Score formula  ·  Savings calculator  │
│  PostgreSQL queries  ·  SendGrid email sender               │
└─────────────────────────────────────────────────────────────┘
```

---

## 5. Phase-by-Phase Plan

### Phase A — Agentic Analyst ✅ COMPLETE (2026-03-22)

**What we have now:**
- Industry classification: exact string match only — `"healthcare"` → 90pts, `"unknown"` → 45pts penalty
- Data gaps: if `employee_count=0` → silently use 0, score penalized
- Score reason: hardcoded template string filled with variables
- No feedback loop: bad data → bad score, never retried

**What changes:**
1. `llm_inspector.py` (new) — LLM reads company name + crawled text → infers industry + detects data gaps → returns action: `score_now` or `enrich_before_scoring`
2. `analyst_agent.gather_company_data()` — calls inspector before scoring, runs re-enrichment loop if needed (max 2 loops)
3. `score_engine.generate_score_reason()` — replaced with LLM narrator that generates text from company context

**How it works:**
```
Load company from DB
  ↓
LLM Data Inspector (~100 tokens):
  Input:  name, website, industry, employee_count, site_count, crawled_text
  Output: { "inferred_industry": "healthcare",
            "data_gaps": ["employee_count"],
            "action": "enrich_before_scoring" }
  ↓
If enrich_before_scoring:
  crawl → Apollo → re-check → LLM re-evaluates
  ↓
score_engine.compute_score(...)   ← unchanged, deterministic
  ↓
LLM Score Narrator (~80 tokens):
  "250-employee healthcare company, 3 sites in deregulated NY —
   strong audit candidate with ~$180k annual savings potential"
```

**Files built:**
- `agents/analyst/llm_inspector.py` — NEW: `inspect_company()` + `generate_score_narrative()` + `_call_llm()` + `_fallback_narrative()`
- `agents/analyst/analyst_agent.py` — UPDATED: `gather_company_data()` wires inspector + re-enrichment loop; `process_one_company()` uses LLM narrator; `run()` logs inspector decisions to `agent_run_logs`

**LLM calls per company:** 2 (~180 tokens). Skipped entirely if all data present.
**Fallback:** any LLM failure falls back silently to rule-based behavior — scoring never blocked.

---

### Phase B — Agentic Scout ✅ COMPLETE (2026-03-22)

**What we had:**
- One fixed query per source: `"{industry} in {location}"`
- No reasoning about what variants to try
- Deduplication: rule-based domain/name match only
- No quality loop: stopped regardless of how few results were found

**What changed:**
1. `llm_query_planner.py` (new) — LLM generates 3–5 search query variants from user intent
2. Scout runs ALL variants across Google Maps + Tavily (each query → separate API call)
3. `llm_deduplicator.py` (new) — domain dedup pass + LLM near-duplicate review (name similarity ≥ 0.75)
4. Quality check: if results < 80% of target → `plan_retry_queries()` → 3 new queries → retry once
5. `google_maps_client.py` — added `query_text` param so planner can override the default query
6. `search_client.py` — added `search_with_queries()` function to accept LLM-planned query list

**How it works:**
```
User: "find schools in Buffalo"
  ↓
LLM Query Planner (~80 tokens):
  ["elementary schools Buffalo NY", "private schools Western New York",
   "K-12 school districts Erie County", "universities Buffalo NY"]
  ↓
Run ALL queries → Google Maps (each query = separate Places API call) + Tavily
  ↓
LLM Deduplicator (~150 tokens per batch):
  Pass 1: domain exact match → drops obvious duplicates
  Pass 2: name-similar pairs → LLM decides: "Buffalo City School District" + "BCSD" → same
  ↓
Quality Check: found 12, target 20 → plan_retry_queries() → 3 more queries → retry once
  ↓
Save to DB
```

**Files built:**
- `agents/scout/llm_query_planner.py` — NEW: `plan_queries()` + `plan_retry_queries()` + `_call_llm()` + `_fallback_queries()` + `_retry_fallback()`
- `agents/scout/llm_deduplicator.py` — NEW: `deduplicate()` + `_rule_dedup()` + `_find_suspicious_pairs()` + `_ask_llm_which_are_duplicates()`
- `agents/scout/scout_agent.py` — UPDATED: query planner wired at start of `run()`, multi-query loop for API sources, LLM dedup before DB save, quality check retry loop
- `agents/scout/google_maps_client.py` — UPDATED: `search_companies()` accepts `query_text` param
- `agents/scout/search_client.py` — UPDATED: added `search_with_queries()` function

**LLM calls per Scout run:** up to 3 (~300 tokens). Fallback on any LLM error — Scout never blocked.

---

### Phase 3 — Agentic Writer + Critic Loop

**What we have now:**
- Template fill → LLM polishes the template
- No quality evaluation of output
- No retry — first LLM response is saved

**What changes:**
1. Writer generates from company context (not template slots) — LLM reasons about which angle works best for this company
2. `critic_agent.py` (new) — evaluates draft on 0–10 rubric, returns score + rewrite instruction
3. Rewrite loop: if score < 7, Writer sees the instruction and rewrites (max 2 loops)
4. Confidence flag: if still < 7 after 2 loops, save with `low_confidence=true`

**How it works:**
```
Writer (~400 tokens):
  Reads company data → reasons about angle → generates full email
  ↓
Critic (~250 tokens):
  Evaluates: personalized? specific number? clear CTA? sounds human?
  Output: { score: 6, reason: "no savings figure",
            instruction: "add $180k estimate in paragraph 2" }
  ↓
If score < 7: Writer rewrites with instruction → Critic re-evaluates (max 2 loops)
If score ≥ 7: save draft → human review queue
```

**Files changed:** `writer_agent.py`, `llm_connector.py`, new `critic_agent.py`
**LLM calls per email:** 2–6 (~1,000 tokens)

---

### Phase D — Chat Dynamic Filters (minor enhancement)

**What we have now:**
- Tier 2 routing uses Python string matching for `tier` and `industry` extraction
- Tools have fixed parameter schemas

**What changes:**
- LLM builds filter combinations from natural language, including combinations Python matching misses
- Context carry-forward: multi-turn filter refinement without restarting

**LLM calls:** already in use (ReAct loop), minimal additional tokens

---

## 6. Memory Model

### Short-term (per run, in-process)
- Company data accumulated during Scout
- Enrichment results per company
- Scores and reasoning per company
- Critic feedback per draft

### Long-term (PostgreSQL tables)
| Table | Tracks | Used by |
|---|---|---|
| `source_performance` | Quality score per source per industry/location | Scout — ranks sources at run start |
| `email_win_rate` | Reply rate per angle per industry | Writer — picks best angle |
| `agent_run_logs` | Every decision + action per run | Observability, debugging |
| `human_approval_requests` | Human review queue + outcomes | Orchestrator |

---

## 7. Token Cost Estimate

Per full pipeline run (20 companies, 5 emails):

| Stage | Calls | Tokens | GPT-4o-mini cost |
|---|---|---|---|
| Scout query planning | 3 | ~300 | $0.00045 |
| Analyst per company ×20 | 40 | ~3,600 | $0.0054 |
| Writer + Critic per email ×5 | 20 | ~5,000 | $0.0075 |
| Chat per message | 1 | ~200 | $0.0003 |
| **Total** | | **~9,100** | **~$0.013** |

With **Ollama (local)**: $0.00 per run.

---

## 8. Observability

Every LLM call is logged to `agent_run_logs` with:
- `agent` — which agent made the call
- `action` — what the LLM was asked to do (e.g. `infer_industry`, `critique_draft`)
- `output_summary` — what it returned (JSON output or score)
- `duration_ms` — how long it took

LangSmith tracing enabled (set `LANGCHAIN_TRACING_V2=true` in `.env`) — shows full LLM trace per run.

---

## 9. Build Order

```
Step 1 → Phase A: Analyst LLM reasoning layer           ✅ DONE (2026-03-22)
         LLM infers industry, detects data gaps, re-enriches, writes narrative reason

Step 2 → Phase B: Scout agentic query planning           ✅ DONE (2026-03-22)
         LLM generates 3–5 query variants, multi-query API calls, LLM dedup, quality retry

Step 3 → Phase 3: Writer + Critic loop                   🔲 NEXT
         Completes the email generation pipeline with quality evaluation

Step 4 → Phase D: Chat dynamic filter generation         🔲 PLANNED
         Already mostly working — small enhancement to filter combinations
```

---

## 10. Success Criteria

| Metric | Target |
|---|---|
| Industry correctly classified | > 90% of companies (vs ~60% with exact string match) |
| Companies scored with real employee_count | > 70% (vs ~30% today) |
| Email draft quality (Critic score) | Average ≥ 7 after at most 1 rewrite |
| Scout query coverage | User intent matched by at least 3 query variants |
| Chat filter accuracy | Correct filters extracted from natural language ≥ 95% |
