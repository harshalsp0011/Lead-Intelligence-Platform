# Agentic Design — Utility Lead Platform

**Last updated:** 2026-03-24
**Status:** Reflects current built system (Phases 0–3 + 2.6 complete)

---

## 1. What "Agentic" Means Here

A traditional automation system executes fixed steps in a fixed order:

```
Automation:   User → fixed code → fixed query → fixed formula → result
```

An agentic system uses an LLM as a **reasoning and decision layer** on top of
deterministic tools (APIs, DB queries, math):

```
Agentic:   User → LLM reasons about intent
                → decides which tools to call and in what order
                → executes tools (APIs, DB, math — deterministic)
                → evaluates result quality
                → loops if result is not good enough
                → returns result
```

**Key principle:** LLM never does math. LLM never calls APIs directly. LLM classifies,
infers, decides, evaluates, and generates text. Everything else is deterministic code.

---

## 2. Agentic Concepts Implemented

| Concept | Plain English | Where Used |
|---|---|---|
| **Tool Use** | LLM picks and calls tools based on intent | Chat Agent |
| **ReAct Loop** | Reason → Act → Observe → repeat until done | Chat Agent |
| **Context Carry-Forward** | Multi-turn memory across chat messages | Chat Agent |
| **Dynamic Query Planning** | LLM generates search variants, not one fixed string | Scout (partial) |
| **Waterfall with Graceful Degradation** | Try provider A → B → C → fallback, never crash | Enrichment |
| **Context-Aware Generation** | LLM reads company signals, reasons before writing | Writer |
| **Self-Critique / Reflection** | Agent evaluates its own output on a rubric | Writer + Critic |
| **Iterative Refinement** | Rewrite loop — max 2 attempts with targeted feedback | Writer |
| **Uncertainty Flagging** | Agent signals when it can't reach confidence threshold | Writer |
| **Human-in-the-Loop (HITL)** | Human approval gates before irreversible actions | Leads + Emails |
| **Observable Execution** | Live counters, run tracking, completion notifications | All agents |
| **Learning from Feedback** | Historical reply rates bias future angle selection | Writer + Tracker |
| **Graceful Degradation** | No contact found → generic draft, not a skip | Writer |

---

## 3. Full Pipeline — Where Agentic Behaviors Fire

```
Scout
  │  [Tool Use] — Chat LLM picks search_companies tool from user intent
  │  [Dynamic Query] — LLM builds query variants (partial — Phase B will complete)
  ▼
companies table

Analyst
  │  [LLM Scoring] — LLM narrates score_reason from company signals
  │  [Data Inference] — Apollo fallback when employee_count missing
  ▼
lead_scores  +  company_features

    ┌─── [HITL Gate 1] ────────────────────────────────────────┐
    │  Human reviews leads on /leads page                      │
    │  Approve → company.status = "approved"                   │
    │  Reject → company excluded from Writer                   │
    └──────────────────────────────────────────────────────────┘

Contact Enrichment
  │  [Waterfall] — Hunter → Apollo → Scraper → Serper →
  │               Snov → Prospeo → ZeroBounce → Permutation → Generic
  │  [Skip Flags] — _hunter_blocked / _apollo_blocked skip after first 429/403
  │  [Quality Gates] — placeholder filter, domain integrity check
  ▼
contacts table

Writer
  │  [Learning] — get_best_angle() reads email_win_rate
  │  [Context-Aware Generation] — LLM reasons about angle before writing
  │  [Self-Critique] — Critic LLM scores draft 0–10
  │  [Iterative Refinement] — rewrite loop (max 2)
  │  [Uncertainty Flagging] — low_confidence=True if never reaches 7/10
  │  [Observable Execution] — AgentRun.drafts_created counter, notification email
  ▼
email_drafts table

    ┌─── [HITL Gate 2] ────────────────────────────────────────┐
    │  Human reviews drafts on /emails page                    │
    │  Approve → email sent immediately via SendGrid           │
    │  Reject → draft deleted, company reset to "approved"     │
    │  Edit+Approve → human edits, then sends                  │
    │  Regenerate → new Writer+Critic cycle                    │
    └──────────────────────────────────────────────────────────┘

Outreach (Phase 4)
  │  Send approved emails + follow-ups
  ▼
outreach_events table

Tracker (Phase 4)
  │  [Learning Write] — updates email_win_rate on reply events
  │  [Alert] — SendGrid notification to sales team on positive reply
  ▼
email_win_rate  (feeds back to Writer on next run)
```

---

## 4. Concept Deep Dives

### 4.1 Tool Use + ReAct Loop (Chat Agent)

**Concept:** LangChain ReAct (Reason + Act) — the LLM reasons about user intent,
picks a tool, observes the result, and decides whether to call another tool or respond.

**Tech:** LangChain `create_react_agent`, system prompt, tool list

**Implementation:** `agents/analyst/analyst_agent.py`, `api/routes/chat.py`

```
User: "find 10 healthcare companies in Buffalo"
  ↓
LLM reasons: "user wants to discover companies → call search_companies"
  ↓
Calls: search_companies(industry="healthcare", location="Buffalo NY", count=10)
  ↓
Observes: 10 companies saved to DB
  ↓
LLM responds: "Found 10 healthcare companies in Buffalo — 3 high, 5 medium, 2 low tier"
```

Three-tier routing decides how much LLM power to use:
- **Tier 1 — Conversational:** "thanks" → direct reply, no tools
- **Tier 2 — Intent parser:** simple data query → Python extracts filters, calls tool directly
- **Tier 3 — Agent loop:** complex/multi-step → full LangChain ReAct

**Why:** Tier 1 and 2 avoid unnecessary LLM calls for simple tasks — faster, cheaper, more reliable.

---

### 4.2 Waterfall with Graceful Degradation (Contact Enrichment)

**Concept:** A sequence of providers where each failure silently falls through to the
next. No single provider crashing stops the pipeline.

**Tech:** Python `try/except` per step, module-level skip flags, ordered fallback chain

**Implementation:** `agents/analyst/enrichment_client.py`

```python
# Every step wrapped — failure falls through
try:
    contacts = find_via_hunter(domain)
except Exception:
    pass  # fall through to Apollo

try:
    contacts = find_via_apollo(domain)
except Exception:
    pass  # fall through to scraper
# ... 8 steps total
```

**Skip flags** (`_hunter_blocked`, `_apollo_blocked`): once a provider returns 429/403,
all remaining companies in the run skip that provider — no wasted API calls.

**Why:** Hunter 429 and Apollo 403 used to crash the entire enrichment run. Now they
fail silently. Every company gets a best-effort result from whatever provider is available.

The 8-step waterfall:
1. Hunter (domain search) — 50 searches/month
2. Apollo (people search) — blocked on free tier
3. Website scraper (mailto: + regex) — free, limited by JS forms
4. Serper / SerpAPI (Google search for emails) — 2,500/month
5. Snov.io (domain bulk search) — requires paid plan
6. Prospeo (LinkedIn search+enrich, two-step) — 100 enrich credits/month
7. ZeroBounce guessformat + name search — 10 domain lookups/month
8. 8-pattern permutation (firstname.lastname@...) — verified by ZeroBounce
9. Generic inbox fallback (info@domain.com) — last resort

---

### 4.3 Context-Aware Generation (Writer)

**Concept:** Instead of filling template placeholders, the LLM reads company context
and decides the angle, tone, and content before writing a single word.

**Tech:** LLM prompt with `REASONING:` section, company profile, analyst note, contact

**Implementation:** `agents/writer/writer_agent.py` — `_WRITER_PROMPT`, `_write_draft()`

The prompt contains:
- Company name, industry, city, state, site count
- Estimated annual savings (low / mid / high)
- Whether the state is deregulated
- `score_reason` — the Analyst's narrative (e.g. "3-site healthcare org in deregulated NY, strong utility spend signal — ~$180k annual savings potential")
- Contact first name and title
- Win rate hint (if available): which angle has the highest reply rate in this industry

The LLM outputs `REASONING:` (2–3 sentences), `ANGLE:`, `SUBJECT:`, and `BODY:`.

```
REASONING: Healthcare company with 3 sites in deregulated NY — electricity cost
           is the primary lever. VP of Operations will care about budget predictability
           more than raw savings. Lead with audit offer to reduce commitment friction.
ANGLE: audit_offer
SUBJECT: Free energy audit for Regional General Hospital — 3 sites, $180k opportunity
BODY: Hi Sarah, ...
```

**Why:** Template-filling produces generic, robotic emails regardless of company context.
A CFO at a 3-site hospital gets the same email as a solo-site retail store. Context-aware
generation produces emails that read like someone actually researched the company.

---

### 4.4 Self-Critique + Iterative Refinement (Writer + Critic)

**Concept:** A second LLM call evaluates the first LLM's output on a rubric. If quality
is below threshold, the writer rewrites with the specific feedback. Max 2 loops.

**Tech:** Two-LLM pattern — Writer LLM + Critic LLM as separate calls

**Implementation:** `agents/writer/critic_agent.py`, `agents/writer/writer_agent.py`

```
Write draft (LLM call 1)
  ↓
Critic evaluates (LLM call 2):
  score=6, feedback="No savings figure. Subject too generic. Add $180k in para 2."
  ↓
Score < 7 → rewrite with feedback (LLM call 3)
  ↓
Critic re-evaluates (LLM call 4):
  score=8, passed=True
  ↓
Save draft
```

**Critic rubric** (5 criteria × 2 points = 10 max):

| Criterion | Pass condition |
|---|---|
| Personalised | Mentions company name or a specific detail about them |
| Specific number | Contains a dollar figure, not just "significant savings" |
| Clear CTA | One specific ask — call, audit, or reply to schedule |
| Sounds human | Not template-like — reads like a person wrote it |
| Subject line | Specific to this company, not generic ("Quick question") |

**Threshold:** ≥ 7 to pass. < 7 → rewrite. Still < 7 after 2 rewrites → `low_confidence=True`.

**Why:** Without evaluation, whatever the LLM produces on the first try gets sent. LLMs
frequently produce generic or vague first drafts. The Critic catches this before a human
wastes time reviewing a clearly bad draft. In practice, ~60–70% of drafts pass on
first try; the rest need 1–2 rewrites.

---

### 4.5 Uncertainty Flagging (Writer)

**Concept:** When the agent cannot reach its own quality threshold after all retries,
it explicitly signals uncertainty rather than silently passing a low-quality result.

**Tech:** `low_confidence` boolean on `EmailDraft`, warning banner in UI

**Implementation:** `agents/writer/writer_agent.py` (sets flag), `dashboard/src/pages/EmailReview.jsx` (shows banner)

```python
low_confidence = not critic_result["passed"]  # True if never passed after all rewrites
```

The Email Review page shows a red banner on `low_confidence=True` drafts:
> "⚠ AI low confidence — draft did not reach score 7/10 after rewrites. Review carefully before sending."

**Why:** Silently saving a 5/10 draft would mislead the reviewer. Flagging it explicitly
tells the human: "the AI struggled here, pay extra attention." The human can then
reject it and regenerate, or edit it themselves.

---

### 4.6 Human-in-the-Loop (HITL) Gates

**Concept:** The pipeline pauses at defined checkpoints for human review before
irreversible actions (emailing a prospect, marking a company as contacted).

**Tech:** `approved_human` field on `LeadScore` and `EmailDraft`, approval API endpoints,
`HumanApprovalRequest` table, SendGrid notification emails

**Two gates:**

**Gate 1 — Lead Approval** (after Analyst scores):
- Human reviews leads on `/leads` page
- Approves or rejects each lead
- Only approved leads proceed to enrichment and Writer
- Notification: SendGrid email lists scored leads with tier + savings, links to `/leads`

**Gate 2 — Draft Approval** (after Writer generates):
- Human reviews drafts on `/emails` page
- Options: Approve & Send | Edit + Approve | Reject | Regenerate
- Approve triggers immediate SMTP send via SendGrid
- Reject deletes draft, resets company to `approved` (re-appears in Writer queue)
- Notification: SendGrid email lists all drafts with subject lines + AI scores, links to `/emails`

**Why:** LLM output is probabilistic — it can produce confident but wrong results. A
misaddressed email or a draft with incorrect facts could damage a sales relationship.
Human gates ensure no external action happens without human sign-off. The system
provides the intelligence; the human provides the accountability.

---

### 4.7 Learning from Feedback (Writer + Tracker)

**Concept:** The system tracks which email angles generate replies, and uses that
history to bias future email generation toward what has worked.

**Tech:** `email_win_rate` table, `get_best_angle()` in writer, Tracker updates on reply events

**Implementation:**
- `agents/writer/writer_agent.py` — `get_best_angle(industry, db_session)`
- `agents/tracker/tracker_agent.py` — updates `email_win_rate` on reply (Phase 4)
- `database/orm_models.py` — `EmailWinRate` ORM model

**The feedback loop:**

```
Writer picks angle "audit_offer" for Healthcare company
  ↓
email_drafts.template_used = "audit_offer"
  ↓
Email sent, prospect replies positively
  ↓
Tracker: email_win_rate WHERE industry="Healthcare" AND template_id="audit_offer"
  → replies_received += 1
  → reply_rate = replies_received / emails_sent
  ↓
Next Writer run for Healthcare company:
  get_best_angle("Healthcare") returns "audit_offer" (highest reply_rate)
  → WIN RATE HINT injected into prompt
  → LLM prefers this angle unless company signals suggest otherwise
```

**Cold start protection:** Minimum 5 emails sent before win rate data is trusted
(`_WIN_RATE_MIN_SENT = 5`). Below this, the hint is omitted and LLM picks freely.

**The 5 trackable angles:**

| Angle | Lead with |
|---|---|
| `cost_savings` | Dollar savings estimate |
| `audit_offer` | Free no-commitment energy audit |
| `risk_reduction` | Utility cost volatility / budget risk |
| `multi_site_savings` | Multi-location efficiency |
| `deregulation_opportunity` | Open energy market / supplier switch |

**Why:** Without feedback, every email for every company in an industry gets the same
angle forever — even if that angle never works. With `email_win_rate`, the system
learns which framing resonates with decision-makers in each industry over time.
This requires no code changes — just data accumulation.

---

### 4.8 Observable Execution (All Agents)

**Concept:** Every agent run is tracked in the database with live counters so humans
can see progress, diagnose issues, and verify completion.

**Tech:** `agent_runs` table, `agent_run_logs` table, `/pipeline/run/{run_id}` endpoint,
`send_draft_approval_request()` email notification

**Implementation:** `agents/orchestrator/orchestrator.py` — `run_writer()` creates `AgentRun`

What gets tracked per Writer run:
- `status`: `writer_running` → `writer_awaiting_approval` (or `failed`)
- `current_stage`: `writer_running` → `writer_complete`
- `companies_approved`: how many companies were eligible
- `drafts_created`: incremented after each draft (live counter visible on Triggers page)
- `completed_at`: when Writer finished

**Why:** Without run tracking, the frontend can only say "running..." or "done". With
`agent_runs`, the Triggers page can show "3/8 drafts created" in real time, the Pipeline
page shows current stage, and failed runs can be diagnosed from `error_message`.

---

## 5. What Is NOT Agentic (Intentionally)

Some parts of the system deliberately stay rule-based and deterministic:

| Component | Why it stays rule-based |
|---|---|
| Score formula | `Score = (Recovery × 0.40) + (Industry × 0.25) + ...` — LLM would hallucinate numbers |
| DB queries | SQL is deterministic and auditable — LLM-generated SQL is unpredictable |
| Email sending | No reasoning needed — if approved, send. Provider choice is config. |
| Score thresholds | Business rules (≥70 = high) — not a judgment call |
| Phone lookup | Waterfall of APIs returning structured data — no reasoning involved |

**Principle:** Use LLM where reasoning, inference, or language generation adds value.
Use deterministic code where correctness and auditability matter more than flexibility.

---

## 6. Technology Stack for Agentic Features

| Feature | Library / Tool | Why |
|---|---|---|
| Chat ReAct loop | LangChain `create_react_agent` | Managed tool-calling loop with history |
| Writer + Critic LLM calls | `llm_connector.py` wrapping Ollama / OpenAI | Provider-agnostic, easy to swap |
| LLM (default) | Ollama + llama3.2 (local) | Zero cost, no data leaves the machine |
| LLM (optional) | OpenAI GPT-4o-mini | Faster, better quality, ~$0.0015/email |
| Run tracking | SQLAlchemy + `agent_runs` table | Persistent, queryable, survives restarts |
| Notifications | SendGrid (`email_notifier.py`) | Reliable delivery, same provider as outreach |
| Learning memory | PostgreSQL `email_win_rate` | Durable, queryable, no extra infra |
| Waterfall state | Module-level flags (`_hunter_blocked`) | Simple, zero-overhead, process-scoped |

---

## 7. Agentic Maturity by Agent

| Agent | Current Agentic Level | Planned Upgrade |
|---|---|---|
| **Chat** | Full ReAct loop, tool use, multi-turn context | — |
| **Writer** | Context-aware generation, Critic loop, learning, uncertainty flagging | — |
| **Enrichment** | Waterfall with graceful degradation, quality gates | — |
| **Analyst** | LLM score narration, Apollo data gap fallback | Phase A: LLM industry inference, full data gap detection loop |
| **Scout** | LLM intent extraction for search query | Phase B: LLM query planning, parallel search, quality loop, deduplication |
| **Tracker** | Rule-based reply detection | Phase 4: sentiment classification, win rate updates |
| **Outreach** | Rule-based send + followup scheduling | Phase 4: send + followup logic |
