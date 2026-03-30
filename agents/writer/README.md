# Writer Agent

**Role:** Generate personalized outreach email drafts for every approved company. A second AI (the Critic) reviews every draft and the Writer rewrites it if the score is too low. No email is sent until a human approves it on the Email Review page.

**Agentic pattern:** Writer → Critic → Reflect → Rewrite loop (max 2 rewrites). Reads `email_win_rate` history to bias angle selection toward what has worked.
**LLM calls per email:** 2–6 (1 write + 1 critic + up to 2 rewrites × 1 critic each).
**Triggered by:** `POST /trigger/writer` → Orchestrator → Task Manager → `writer_agent.run()`

---

## Table of Contents

1. [The Problem Writer Solves](#1-the-problem-writer-solves)
2. [File Architecture](#2-file-architecture)
3. [How Each File Works](#3-how-each-file-works)
4. [The Agentic Loop — Writer Critic Reflect Rewrite](#4-the-agentic-loop)
5. [Full Execution Flow](#5-full-execution-flow)
6. [System Prompts — Exact Text](#6-system-prompts--exact-text)
7. [The 5 Email Angles](#7-the-5-email-angles)
8. [Win Rate Learning — How It Works](#8-win-rate-learning)
9. [The Critic — All 5 Criteria and Exact Scoring](#9-the-critic--all-5-criteria-and-exact-scoring)
10. [The low_confidence Flag](#10-the-low_confidence-flag)
11. [Service Memory — What Gets Embedded](#11-service-memory--what-gets-embedded)
12. [API Calls Made](#12-api-calls-made)
13. [Database Reads and Writes](#13-database-reads-and-writes)
14. [Run Tracking](#14-run-tracking)
15. [How It's Triggered](#15-how-its-triggered)
16. [Fallback and Error Handling](#16-fallback-and-error-handling)
17. [Rejection Flow](#17-rejection-flow)
18. [Data Contract](#18-data-contract)
19. [LLM Usage and Cost](#19-llm-usage-and-cost)

---

## 1. The Problem Writer Solves

After a lead is approved, the sales team still has to write a cold outreach email. Done manually:
- Takes 20–40 minutes per email (reading the company profile, crafting a hook, estimating savings, writing a compelling subject line)
- Quality is inconsistent — some reps are better writers than others
- No feedback loop — no one tracks which email styles actually get replies
- Generic templates get low reply rates

**What Writer does instead:**
- Reads every signal the Analyst collected — industry, size, savings estimate, score reason, deregulated state
- Chooses the angle most likely to work for this company and industry
- Writes a genuinely personalized email — not a template with blanks filled in
- A second AI immediately reviews the draft on 5 specific criteria
- Rewrites if needed (up to twice), then flags low-quality drafts for extra human attention
- Over time, tracks which angles get replies per industry and naturally shifts toward what works

---

## 2. File Architecture

```
agents/writer/
│
├── writer_agent.py       ← ENTRY POINT. Loads context, runs Writer→Critic loop, persists draft.
│                            Called by: orchestrator → task_manager, emails API (regenerate)
│                            Calls: critic_agent, llm_connector, enrichment_client
│
├── critic_agent.py       ← CRITIC LLM. Evaluates draft 0–10 on 5 criteria.
│                            Returns score, pass/fail, one-sentence feedback.
│                            Called by: writer_agent.py
│                            External: Ollama or OpenAI (via LangChain)
│
├── llm_connector.py      ← LLM ROUTER. Abstracts Ollama and OpenAI calls.
│                            Called by: writer_agent.py (for Writer and Rewrite calls)
│                            External: Ollama (local) or OpenAI API
│
├── template_engine.py    ← LEGACY. Industry template loader kept for backward compatibility.
│                            NOT used in main agentic flow.
│                            External: reads data/templates/*.txt files
│
└── tone_validator.py     ← LEGACY. Rule-based spam/length/CTA checks.
                             NOT used in main agentic flow.
                             External: none (pure regex)
```

**Dependency flow:**
```
writer_agent.py
  ├── critic_agent.py              (LangChain → Ollama / OpenAI)
  ├── llm_connector.py             (Ollama or OpenAI direct)
  ├── enrichment_client.get_priority_contact()  (PostgreSQL — read Contact)
  └── [PostgreSQL — read Company, CompanyFeature, LeadScore, EmailWinRate]
      [PostgreSQL — write EmailDraft, update Company.status, update AgentRun.drafts_created]
```

---

## 3. How Each File Works

### `writer_agent.py` — Main Orchestrator

**What it does:** The entry point. For each company ID, loads all context from the database, queries win rate history, builds the prompt, runs the Writer → Critic → Rewrite loop, and saves the final draft.

**Key functions:**

```python
run(company_ids, db_session, run_id=None, on_progress=None) → list[str]
```
Loops over every company ID. Calls `process_one_company()` for each. Updates `AgentRun.drafts_created` counter after each success. Returns list of created draft IDs.

```python
process_one_company(company_id, db_session, on_progress=None) → str | None
```
The core per-company flow. See Section 4 for the full loop detail. Returns draft ID string or None if company/score not found.

```python
get_best_angle(industry, db_session) → str | None
```
Queries `email_win_rate` for the highest `reply_rate` in this industry with at least 5 emails sent. Returns the `template_id` (angle name) or None if not enough data.

```python
_write_draft(context) → (subject, body, angle)
```
Formats `_WRITER_PROMPT` with context, calls `_call_llm()`, parses the output. Returns the subject line, body, and chosen angle name.

```python
_rewrite_draft(subject, body, score, feedback, angle) → (subject, body, angle)
```
Formats `_REWRITE_PROMPT` with the original draft and Critic feedback, calls LLM, parses output. **Preserves the original angle** — a rewrite prompt does not ask for ANGLE: so the LLM doesn't change it.

```python
_parse_writer_output(raw) → (subject, body, angle)
```
Parses the structured LLM response. Looks for `SUBJECT:`, `ANGLE:`, `BODY:` markers. Strips any self-explanation text the LLM adds after the email. Fallbacks: subject = "Utility cost savings opportunity", body = raw text, angle = "cost_savings".

```python
format_savings(amount) → str
```
Formats dollar amounts: `$1.2M`, `$180k`, `$50`. Used in email body and savings range display.

```python
_save_draft(...) → str
```
Creates `EmailDraft` ORM row, flushes, returns draft UUID string.

**Constants:**
```python
_PASS_THRESHOLD = 7.0       # Critic score needed to avoid rewrite
_MAX_REWRITES = 2           # Max rewrite attempts before low_confidence
_WIN_RATE_MIN_SENT = 5      # Min emails sent before win rate data is trusted
_VALID_ANGLES = {
    "cost_savings", "audit_offer", "risk_reduction",
    "multi_site_savings", "deregulation_opportunity"
}
```

---

### `critic_agent.py` — The Critic

**What it does:** A second, independent LLM call that reviews the draft against 5 specific criteria. Returns a score 0–10, a pass/fail result, and one specific sentence telling the Writer exactly what to fix.

**Key function:**

```python
evaluate(subject, body, company_context) → dict
```
Formats `_CRITIC_PROMPT` with the email and company context. Calls LLM. Parses JSON response. **Recalculates score from criteria** (doesn't trust LLM's stated total — it does its own sum). Returns `{score, passed, feedback, criteria}`.

**Why a separate LLM call?**
The Writer is instructed to write well. The Critic is instructed to find flaws. Two separate instructions to the same model produce more reliable results than asking one model to write *and* evaluate simultaneously. The Critic has no stake in the draft — it just evaluates.

**Fallback if Critic LLM fails:**
```python
return {"score": 7.0, "passed": True, "feedback": "", "criteria": {}}
```
Returns a neutral "passing" score to prevent the rewrite loop from running forever when the LLM is unavailable.

---

### `llm_connector.py` — LLM Router

**What it does:** Routes LLM calls to either Ollama (local) or OpenAI based on `LLM_PROVIDER` env var.

**Key functions:**

```python
call_ollama(prompt) → str
# ollama.Client(host=OLLAMA_BASE_URL).chat(model=LLM_MODEL, messages=[...])

call_openai(prompt) → str
# OpenAI().chat.completions.create(model=LLM_MODEL, max_tokens=1000, temperature=0.7)

select_provider() → str
# Returns "ollama" or "openai"; raises ValueError if invalid
```

**Note:** Writer calls this directly for Writer and Rewrite calls. Critic calls through LangChain (`config.llm_config.get_llm()`) — same underlying model, different abstraction layer.

---

### `template_engine.py` — Legacy (Not Used in Main Flow)

Kept for backward compatibility. Was used before the agentic Writer replaced it. Maps industry → template file (e.g., healthcare → `email_healthcare.txt`). Fills `{{placeholders}}` with context values.

Not called by the main `process_one_company()` flow.

---

### `tone_validator.py` — Legacy (Not Used in Main Flow)

Rule-based validator. Checks for 13 spam trigger words, body length (50–250 words), CTA keyword presence, all-caps usage, and unrealistically large savings claims. Was a guardrail before the Critic existed.

Not called by the main flow — the Critic now handles quality evaluation with far more nuance.

---

## 4. The Agentic Loop

### Why This Is Agentic

A fixed template system fills in `{{company_name}}` and `{{savings}}` and calls it done. It has no feedback loop, no self-evaluation, and no ability to improve a draft that isn't good enough.

The Writer is agentic because:
1. **It reasons before writing** — it thinks about which angle fits this specific company before drafting
2. **It reflects on its own output** — a second AI reviews the draft and gives specific feedback
3. **It acts on the feedback** — if the draft isn't good enough, it rewrites with the Critic's specific guidance
4. **It learns from history** — it reads past email win rates and shifts toward angles that work

```
┌──────────────────────────────────────────────────────────────────┐
│                        WRITER LOOP                               │
│                                                                  │
│  OBSERVE     Load company profile, contact, score reason,        │
│              savings estimates, deregulated state                │
│                   ↓                                              │
│  REASON      Query email_win_rate for best angle in industry     │
│              → inject as hint if ≥5 data points exist            │
│                   ↓                                              │
│  ACT         Writer LLM reasons about angle, writes email        │
│              → REASONING: 2-3 sentence justification             │
│              → ANGLE: chosen from 5 options                      │
│              → SUBJECT: specific to company                      │
│              → BODY: 100-160 words with savings + CTA            │
│                   ↓                                              │
│  REFLECT     Critic LLM evaluates on 5 criteria (0-2 each)      │
│              → score 0-10, passed bool, one-sentence feedback    │
│                   ↓                                              │
│  REFLECT     score >= 7? → Save draft. Done.                     │
│              score < 7?  → Rewrite (max 2 times)                 │
│                   ↓                                              │
│  ACT         Rewrite: LLM sees original draft + Critic feedback  │
│              → fixes the specific issue                          │
│              → preserves the angle                               │
│                   ↓                                              │
│  REFLECT     Critic evaluates again                              │
│              → still < 7 after 2 rewrites? → low_confidence=True │
│                   ↓                                              │
│  PERSIST     Save draft with: critic_score, rewrite_count,       │
│              low_confidence, template_used (angle)               │
│                   ↓                                              │
│  LEARN       Tracker later updates email_win_rate when           │
│              a reply comes in for this angle + industry          │
└──────────────────────────────────────────────────────────────────┘
```

### The Loop in Code

```python
# Step 1: Initial draft
subject, body, angle = _write_draft(writer_context)
critic_result = critic_agent.evaluate(subject, body, critic_context)
rewrite_count = 0

# Step 2: Rewrite loop
while not critic_result["passed"] and rewrite_count < _MAX_REWRITES:
    rewrite_count += 1
    subject, body, angle = _rewrite_draft(
        subject, body,
        score=critic_result["score"],
        feedback=critic_result["feedback"],
        angle=angle
    )
    critic_result = critic_agent.evaluate(subject, body, critic_context)

# Step 3: Flag if still failing
low_confidence = not critic_result["passed"]

# Step 4: Save regardless
draft_id = _save_draft(
    ...,
    critic_score=critic_result["score"],
    low_confidence=low_confidence,
    rewrite_count=rewrite_count,
)
```

### What the LLM Decides vs What Code Decides

| Decision | Who decides | Why |
|---|---|---|
| Which angle fits this company | **Writer LLM** | Requires reasoning about company profile, industry, and deregulation context |
| Whether to follow the win rate hint or override it | **Writer LLM** | Requires judgment — "multi-site hint but this is a single-site company" |
| What makes the email weak | **Critic LLM** | Requires reading comprehension and quality judgment |
| Whether to rewrite | **Code** | Deterministic threshold: score < 7.0 → rewrite, no LLM judgment needed |
| Maximum rewrites | **Code (constant)** | Business rule, not a reasoning task |
| Pass threshold | **Code (constant)** | Consistent standard, configured once |
| What gets saved | **Code** | Deterministic DB write |

---

## 5. Full Execution Flow

```
POST /trigger/writer
  │
  ▼
api/routes/triggers.py::trigger_writer()
  └── background_tasks.add_task(_run_writer)
        │
        ▼
orchestrator.run_writer(industry, location, db)
  └── Creates AgentRun: status="writer_running", current_stage="writer_running"
      └── task_manager.assign_task("writer", {company_ids, run_id, on_progress}, db)
            └── writer_agent.run(company_ids, db, run_id, on_progress)
                  │
                  ├── FOR EACH company_id:
                  │     │
                  │     └── process_one_company(company_id, db, on_progress)
                  │           │
                  │           ├── [OBSERVE] Load Company, CompanyFeature, LeadScore
                  │           │     If company or score missing → return None, skip
                  │           │
                  │           ├── [OBSERVE] get_priority_contact(company_id, db)
                  │           │     If no contact → fallback: contact_name="there", contact_id=None
                  │           │
                  │           ├── [REASON] get_best_angle(industry, db)
                  │           │     SELECT email_win_rate WHERE emails_sent >= 5
                  │           │     ORDER BY reply_rate DESC LIMIT 1
                  │           │     If found → inject angle_hint into writer prompt
                  │           │     If not → angle_hint = "" (cold start)
                  │           │
                  │           ├── Build writer_context dict (all company/contact/savings fields)
                  │           ├── Build critic_context dict (same data for Critic)
                  │           │
                  │           ├── [ACT] _write_draft(writer_context)
                  │           │     → format _WRITER_PROMPT with context
                  │           │     → _call_llm() → Ollama or OpenAI
                  │           │     → _parse_writer_output(raw) → (subject, body, angle)
                  │           │
                  │           ├── [REFLECT] critic_agent.evaluate(subject, body, critic_context)
                  │           │     → format _CRITIC_PROMPT
                  │           │     → LLM returns JSON: criteria scores × 5
                  │           │     → recalculate score from criteria (code, not LLM total)
                  │           │     → {score, passed, feedback, criteria}
                  │           │
                  │           ├── WHILE not passed AND rewrite_count < 2:
                  │           │     ├── rewrite_count++
                  │           │     ├── [ACT] _rewrite_draft(subject, body, score, feedback, angle)
                  │           │     │     → format _REWRITE_PROMPT with original + feedback
                  │           │     │     → _call_llm() → new subject + body
                  │           │     │     → angle preserved (not changed on rewrite)
                  │           │     └── [REFLECT] critic_agent.evaluate() again
                  │           │
                  │           ├── low_confidence = not critic_result["passed"]
                  │           │
                  │           ├── [PERSIST] _save_draft()
                  │           │     → EmailDraft row with all fields
                  │           │     → company.status = "draft_created"
                  │           │     → db.commit()
                  │           │
                  │           └── Return draft_id
                  │
                  ├── Update AgentRun.drafts_created = len(created_so_far)
                  └── Return list[draft_id]

After run() completes:
orchestrator → email_notifier.send_draft_approval_request()
  → Sends email to ALERT_EMAIL with draft table + link to /emails
  → Creates HumanApprovalRequest row (approval_type="emails", status="pending")
  → Updates AgentRun: status="writer_awaiting_approval"
```

---

## 6. System Prompts — Exact Text

### Writer Prompt

```
You are writing a cold outreach email on behalf of a utility cost consulting firm.
Your goal: get a 15-minute intro call or a free energy audit scheduled.

== COMPANY PROFILE ==
Company:   {company_name}
Industry:  {industry}
Location:  {city}, {state}
Sites:     {site_count} location(s)
Est. annual utility savings: {savings_mid} (range: {savings_low} – {savings_high})
Deregulated state: {deregulated}
Analyst note (why this company is a good fit):
  {score_reason}

== CONTACT ==
Name:  {contact_name}
Title: {contact_title}

{angle_hint}== AVAILABLE ANGLES ==
Choose one angle that best fits this company:
- cost_savings         : lead with the dollar savings estimate
- audit_offer          : lead with a free no-commitment energy audit
- risk_reduction       : lead with utility cost volatility / budget risk
- multi_site_savings   : lead with multi-location efficiency opportunity
- deregulation_opportunity : lead with open energy market / supplier switch

== YOUR TASK ==
First, reason (2–3 sentences) about what angle will work best for this specific company.
Consider: their industry, number of sites, savings potential, the analyst note, and their state.
Pick the angle name from the list above.

Then write the email. Requirements:
- Subject line: specific to this company (include name or a detail), not generic
- Opening: reference something specific about them (expansion, industry, location)
- Body: mention the savings estimate (use the mid figure)
- CTA: one clear ask — free audit, 15-min call, or reply to schedule
- Sign-off: professional, from the consulting firm
- Length: 100–160 words for the body (not too long, not too short)
- Tone: warm, direct, human — not template-like or salesy

Return in this exact format:
REASONING: <your 2–3 sentence reasoning>
ANGLE: <one angle name from the list above>
SUBJECT: <subject line>
BODY:
<full email body>
```

### Rewrite Prompt

```
You wrote an outreach email that was reviewed and needs improvement.

== ORIGINAL EMAIL ==
Subject: {subject}

{body}

== CRITIC FEEDBACK ==
Score: {score}/10
Issue: {feedback}

== TASK ==
Rewrite the email to fix the issue above. Keep everything that was good.
Same format — return:
SUBJECT: <subject line>
BODY:
<full email body>
```

**Note:** The rewrite prompt does NOT ask for ANGLE: — the angle is preserved from the original draft in code.

### Critic Prompt

```
You are a B2B email quality reviewer for a utility cost consulting firm.
Evaluate this outreach email draft against the rubric below.

== COMPANY CONTEXT ==
Company: {company_name}
Industry: {industry}
City: {city}, {state}
Sites: {site_count}
Est. annual savings: {savings_mid}
Score reason from analyst: {score_reason}
Contact: {contact_name} ({contact_title})

== EMAIL DRAFT ==
Subject: {subject}

{body}

== RUBRIC (score each 0, 1, or 2) ==
1. personalization  — mentions company name or a specific detail about them (not generic boilerplate)
2. savings_figure   — contains a specific dollar or % savings estimate (not vague "significant savings")
3. clear_cta        — has a specific next step: "free audit", "15-min call", "reply to schedule" etc.
4. human_tone       — reads like a real person wrote it, not a template or AI
5. subject_quality  — subject is specific to this company (not "Quick question" / "Hello" / "Checking in")

Return ONLY this JSON — no explanation, no markdown:
{
  "criteria": {
    "personalization": <0|1|2>,
    "savings_figure":  <0|1|2>,
    "clear_cta":       <0|1|2>,
    "human_tone":      <0|1|2>,
    "subject_quality": <0|1|2>
  },
  "score": <total 0-10>,
  "passed": <true if score >= 7>,
  "feedback": "<one sentence: what is the biggest weakness and exactly how to fix it>"
}
```

---

## 7. The 5 Email Angles

The Writer picks one angle per email. The angle shapes the opening, hook, and CTA.

| Angle | Lead with | Best for |
|---|---|---|
| `cost_savings` | Dollar savings estimate up front | Companies where savings potential is large and concrete |
| `audit_offer` | Free no-commitment energy audit | Companies skeptical of unsolicited outreach — low-risk ask |
| `risk_reduction` | Utility cost volatility / budget risk | Industries with unpredictable energy costs (manufacturing, cold storage) |
| `multi_site_savings` | Multi-location efficiency opportunity | Companies with 3+ sites — aggregate savings across all locations |
| `deregulation_opportunity` | Open energy market / supplier switch | Companies in deregulated states who likely don't know they can switch |

**How the angle is saved:** `email_drafts.template_used = "audit_offer"` (for example). The Tracker reads this field when a reply event occurs to update `email_win_rate`.

---

## 8. Win Rate Learning

### How It Works

The Writer reads the `email_win_rate` table before drafting to see which angle has historically worked best for this industry.

```sql
-- What the Writer queries before drafting
SELECT template_id, reply_rate, emails_sent
FROM email_win_rate
WHERE industry = 'healthcare'
  AND emails_sent >= 5          -- cold-start protection
ORDER BY reply_rate DESC
LIMIT 1
```

**Cold start (no data yet):** `angle_hint = ""` — no win rate section in the prompt. LLM picks freely based on company context.

**With history:** The hint is injected into the Writer prompt:
```
== WIN RATE HINT ==
For healthcare, the angle 'audit_offer' has the highest reply rate based on past emails.
Prefer this angle unless the company signals strongly suggest otherwise.
```

The Writer LLM is instructed to *prefer* the hint but can override it if company context strongly suggests a different angle is better. This is an intentional design — the hint nudges, not forces.

### How the Table Gets Updated

After the Outreach agent sends an email, the Tracker agent monitors for open/click/reply events. When a reply event occurs:

```python
# Tracker updates after reply:
email_win_rate.emails_sent += 1
email_win_rate.replies_received += 1
email_win_rate.reply_rate = replies_received / emails_sent
# Keyed by (template_id=angle, industry=company.industry)
```

After 5+ replies for a given angle + industry combination, the win rate becomes reliable enough to influence future Writer runs.

### The Learning Cycle

```
Writer drafts email → saves template_used="audit_offer"
  ↓
Outreach sends email
  ↓
Prospect replies
  ↓
Tracker records: reply_rate for audit_offer/healthcare improves
  ↓
Next Writer run for healthcare: gets angle hint "audit_offer"
  ↓
More healthcare emails use audit_offer → more data → more reliable hint
```

No one manually configures this. It self-calibrates.

---

## 9. The Critic — All 5 Criteria and Exact Scoring

### Rubric

Each criterion is scored 0, 1, or 2:
- **2** = fully met
- **1** = partially met
- **0** = not met

| Criterion | What it checks | Example of 2 | Example of 0 |
|---|---|---|---|
| `personalization` | Mentions company name or a specific detail about them | "I noticed Midwest Surgical recently opened their 3rd campus..." | "I hope this email finds you well..." |
| `savings_figure` | Contains a specific dollar or % savings estimate | "typically recover $45–80k annually" | "significant potential savings" |
| `clear_cta` | One specific next step — free audit, 15-min call, reply to schedule | "Would you be open to a 15-minute call next week?" | "Let me know if you're interested" |
| `human_tone` | Reads like a real person wrote it, not a template | Natural phrasing, specific context, conversational | "I am writing to inform you of our services..." |
| `subject_quality` | Subject specific to this company, not generic | "Midwest Surgical's 3 Ohio sites — $45k in savings?" | "Quick question" / "Following up" |

**Total: 5 criteria × 2 pts = max 10 pts**

### Scoring Logic

The Critic LLM returns JSON with a `score` field. **The code ignores the LLM's stated total and recalculates it from the individual criteria** — this guards against arithmetic errors in the LLM response:

```python
# Recalculate score from criteria (not from LLM's stated total)
score = float(sum(
    int(criteria.get(k, 0))
    for k in ("personalization", "savings_figure", "clear_cta", "human_tone", "subject_quality")
))
passed = score >= 7.0  # Pass threshold
```

### Pass/Fail Decision

| Score | Decision |
|---|---|
| **≥ 7.0** | Passed — save draft |
| **< 7.0** | Failed — rewrite (up to 2 times) |
| **< 7.0 after 2 rewrites** | Failed — save with `low_confidence=True` |

---

## 10. The low_confidence Flag

### When It's Set

```python
low_confidence = not critic_result["passed"]
# Set AFTER the rewrite loop — so only if final score is still < 7.0
```

This happens when:
1. First draft scores < 7.0
2. Rewrite 1 scores < 7.0
3. Rewrite 2 scores < 7.0 → `low_confidence = True`

### What Happens to Low-Confidence Drafts

- **Still saved** — not discarded. Human reviewer may have context the LLM lacked.
- **Flagged in Email Review UI** — shown with a yellow warning banner and the Critic score
- **Counted in `AgentRun.drafts_created`** — not filtered out from the total
- **Human can:** approve anyway, edit and approve, reject and regenerate, or skip

### Why Not Discard Them?

A draft that scores 6.5/10 may be good enough to send — the Critic is strict. The human has context the Critic doesn't: knowing the contact personally, knowing the company's current situation, knowing the timing is right. The flag exists to make the human look more carefully, not to block sending.

---

## 11. Service Memory — What Gets Embedded

The Writer has access to all of this context when drafting. This is the "service memory" — everything the system knows about the prospect and (via the score reason) about the service offering.

### Writer Context Dictionary

```python
writer_context = {
    "company_name":  "Midwest Surgical Associates",
    "industry":      "healthcare",
    "city":          "Columbus",
    "state":         "OH",
    "site_count":    3,
    "savings_low":   "$28k",           # format_savings(savings_low)
    "savings_mid":   "$38k",           # format_savings(savings_mid)  ← used in body
    "savings_high":  "$48k",           # format_savings(savings_high)
    "deregulated":   "yes",            # "yes" or "no"
    "score_reason":  "3-site healthcare operator in deregulated Ohio — strong savings candidate at ~$38k annually.",
    "contact_name":  "David",          # first name extracted from full_name
    "contact_title": "VP of Facilities",
    "angle_hint":    "== WIN RATE HINT ==\nFor healthcare, the angle 'audit_offer' has the highest reply rate...\n\n"
    # OR: ""  (if cold start / no data)
}
```

**What `score_reason` carries:** The Analyst's LLM-generated explanation of why this company scored well. This line is the most valuable input for the Writer — it tells the Writer *why this company matters* in plain English, not just raw numbers. The Writer can reference this in the email to make it feel informed and specific.

### Critic Context Dictionary

```python
critic_context = {
    "company_name":  "Midwest Surgical Associates",
    "industry":      "healthcare",
    "city":          "Columbus",
    "state":         "OH",
    "site_count":    "3",
    "savings_mid":   "$38k",
    "score_reason":  "3-site healthcare operator in deregulated Ohio...",
    "contact_name":  "David",
    "contact_title": "VP of Facilities"
}
```

The Critic receives the same context so it can evaluate whether the email actually uses the specific details it had access to.

---

## 12. API Calls Made

### Writer LLM Call (via `llm_connector.py`)

**Ollama (default):**
```python
client = ollama.Client(host=settings.OLLAMA_BASE_URL)
# Default: http://host.docker.internal:11434
response = client.chat(
    model=settings.LLM_MODEL,  # Default: llama3.2
    messages=[{"role": "user", "content": prompt}]
)
```

**OpenAI (optional):**
```python
response = OpenAI(api_key=settings.OPENAI_API_KEY).chat.completions.create(
    model=settings.LLM_MODEL,  # e.g., gpt-4o-mini
    messages=[{"role": "user", "content": prompt}],
    max_tokens=1000,
    temperature=0.7
)
```

### Critic LLM Call (via `LangChain` in `critic_agent.py`)

```python
llm = get_llm()  # Returns ChatOllama or OpenAI client via config.llm_config
response = llm.invoke([HumanMessage(content=prompt)])
return str(response.content).strip()
```

Same underlying model as Writer, accessed through LangChain wrapper.

**No other external API calls.** Writer does not call SendGrid, webhooks, or any other service. All output is database writes.

---

## 13. Database Reads and Writes

### Reads

| Table | What is read | Conditions | Why |
|---|---|---|---|
| `companies` | id, name, industry, city, state, site_count | By company_id | Company profile for prompt |
| `company_features` | estimated_site_count, savings_low/mid/high, deregulated_state | By company_id, latest by `computed_at` | Savings estimates for prompt |
| `lead_scores` | score, score_reason, tier, approved_human | By company_id, latest by `scored_at` | Score reason for prompt context |
| `contacts` | id, full_name, title, email | By company_id, `unsubscribed=False` | Contact name/title for personalization |
| `email_win_rate` | template_id, reply_rate, emails_sent | `industry=X AND emails_sent >= 5`, highest reply_rate | Angle hint for prompt |
| `agent_runs` | id, drafts_created | By run_id (optional) | Update live progress counter |

### Writes

| Table | Action | Columns written | When |
|---|---|---|---|
| `email_drafts` | INSERT | `id, company_id, contact_id, subject_line, body, savings_estimate, template_used, critic_score, low_confidence, rewrite_count, approved_human=False, created_at` | After loop completes, in `_save_draft()` |
| `companies` | UPDATE | `status="draft_created"`, `updated_at=now()` | After draft saved |
| `agent_runs` | UPDATE | `drafts_created=len(created)` | After each successful draft |

### Transaction Model

```python
db_session.flush()    # After creating EmailDraft (gets the ID without committing)
db_session.commit()   # After updating Company.status
db_session.rollback() # On any exception — isolates failures per company
```

---

## 14. Run Tracking

### AgentRun Updates

```python
# At start of run — set by orchestrator before calling task_manager:
AgentRun.status = "writer_running"
AgentRun.current_stage = "writer_running"

# After each successful draft — set by writer_agent.run():
AgentRun.drafts_created = len(created)  # running total

# At completion — set by orchestrator after run() returns:
AgentRun.status = "writer_awaiting_approval"
AgentRun.current_stage = "writer_complete"
```

### Progress Callbacks

The `on_progress` callback (passed from orchestrator) is called at each step:

```python
# When starting a company:
on_progress({"step": "✍️ Writing", "company": name, "done": False})

# When running Critic:
on_progress({"step": "🔍 Critic", "company": name, "done": False})

# When rewriting:
on_progress({"step": "↩️ Rewrite 1/2", "company": name, "done": False})

# When done:
on_progress({
    "step": "✅ Done" or "⚠️ Low confidence" or "❌ Failed",
    "company": name,
    "done": True,
    "critic_score": 8.2,
    "rewrites": 1,
    "low_confidence": False
})
```

These callbacks drive the live progress display on the Triggers page.

### Notification Email After Completion

After all drafts are saved, the orchestrator calls `email_notifier.send_draft_approval_request()` which sends to `ALERT_EMAIL`:

- Table: Company | Contact | Subject Line | Angle | AI Score
- Yellow warning banner if any `low_confidence=True` drafts exist
- Explicit note: "No emails have been sent yet"
- "Review & Approve Drafts →" button linking to `/emails`
- Creates `HumanApprovalRequest` row: `approval_type="emails"`, `status="pending"`

---

## 15. How It's Triggered

**Via dashboard:**
Triggers page → Run Writer → Submit

**Via API:**
```bash
curl -X POST http://localhost:8001/trigger/writer \
  -H "Content-Type: application/json"
# Writer runs for all companies with approved_human=True and no existing draft
```

**Via full pipeline:**
```bash
curl -X POST http://localhost:8001/trigger/full \
  -H "Content-Type: application/json" \
  -d '{"industry": "healthcare", "location": "Buffalo NY", "count": 10}'
# Scout → Analyst → Writer chain
```

**Via Email Review page — Regenerate button:**
```python
# DELETE existing draft → reset company.status="approved"
# → writer_agent.process_one_company(company_id, db)
# New draft created from scratch, new Critic loop runs
```

**Via chatbot:**
```
"Write emails for all approved leads"
"Generate a draft for Midwest Surgical"
```

**Poll progress:**
```bash
GET http://localhost:8001/trigger/{trigger_id}/status
# Returns live log messages visible on Triggers page
```

---

## 16. Fallback and Error Handling

| Failure | What happens |
|---|---|
| Company or LeadScore not found in DB | Log warning, return None, skip company |
| No contact found for company | Fallback: `contact_name="there"`, `contact_id=None` — draft still written to "[Company] team" |
| LLM returns unparseable output | Fallback: `subject="Utility cost savings opportunity"`, `body=raw text`, `angle="cost_savings"` |
| LLM strips explanation text after email | `_strip_llm_explanation()` removes everything after "i made the following", "here's what i changed", etc. |
| Angle not in `_VALID_ANGLES` | Fallback to `"cost_savings"` |
| Critic LLM fails | Returns `{score: 7.0, passed: True}` — neutral pass prevents infinite loop |
| Rewrite loop exhausts 2 attempts | Sets `low_confidence=True`, saves draft anyway |
| Individual company exception | `db.rollback()`, log exception, emit "❌ Failed" callback, continue to next company |
| `email_win_rate` has no data for industry | `angle_hint = ""` — LLM picks freely (cold start) |

---

## 17. Rejection Flow

When a human rejects a draft on the Email Review page:

```
Human clicks Reject on Email Review page
  ↓
PATCH /emails/{draft_id}/reject
  ↓
1. Delete email_drafts row
2. Update company.status: "draft_created" → "approved"
3. Return success
  ↓
Company re-appears in "✉️ Generate Drafts" count on Triggers page
Human can:
  - Click "Run Writer" → new draft created from scratch
  - Click "Regenerate" next to the company → writer_agent.process_one_company() runs directly
```

The regenerated draft goes through the full Writer → Critic → Rewrite loop again — it's not just a re-roll of the same prompt. The angle might differ, the writing will differ.

---

## 18. Data Contract

### Input Requirements

Writer expects companies that are:
- `lead_scores.approved_human = True` (human approved on Leads page)
- No existing row in `email_drafts` for this company

### Output Per Company

| Table | Field | Value | Notes |
|---|---|---|---|
| `email_drafts` | `subject_line` | LLM-generated | Specific to company, not generic |
| `email_drafts` | `body` | LLM-generated | 100–160 words, includes savings figure + CTA |
| `email_drafts` | `template_used` | angle name | One of the 5 valid angles |
| `email_drafts` | `critic_score` | 0.0 – 10.0 | Final score after any rewrites |
| `email_drafts` | `low_confidence` | bool | True if final score < 7.0 |
| `email_drafts` | `rewrite_count` | 0, 1, or 2 | How many rewrites happened |
| `email_drafts` | `contact_id` | UUID or NULL | NULL if no contact found |
| `email_drafts` | `approved_human` | False | Set True by approval endpoint |
| `companies` | `status` | "draft_created" | Updated after draft saved |

### What Happens When Data Is Missing

| Missing | Writer's response |
|---|---|
| No contact in DB | Writes to "there" (generic), `contact_id=NULL` |
| No `score_reason` | Uses fallback: "Strong utility spend signals." |
| No `savings_low/mid/high` | `format_savings(0)` → "$0" — scores low but draft still created |
| No `site_count` | Defaults to 1 |
| `deregulated_state` missing | Shown as "no" in prompt |
| No win rate data | No angle hint — LLM picks freely |

---

## 19. LLM Usage and Cost

### Calls Per Email

| Call | When | Approximate tokens |
|---|---|---|
| Writer — initial draft | Every company | ~600 prompt + ~300 response = ~900 |
| Critic — initial evaluation | Every company | ~400 prompt + ~100 response = ~500 |
| Writer — rewrite 1 | If score < 7.0 | ~400 prompt + ~300 response = ~700 |
| Critic — rewrite 1 evaluation | If score < 7.0 | ~400 prompt + ~100 response = ~500 |
| Writer — rewrite 2 | If still < 7.0 | ~400 prompt + ~300 response = ~700 |
| Critic — rewrite 2 evaluation | If still < 7.0 | ~400 prompt + ~100 response = ~500 |

**Total per email (worst case — 2 rewrites):** ~3,800 tokens

### Cost

| Provider | Best case (no rewrites) | Worst case (2 rewrites) |
|---|---|---|
| Ollama (local) | $0 | $0 |
| OpenAI GPT-4o-mini | ~$0.0007 | ~$0.0019 |

Switch provider: set `LLM_PROVIDER=openai` in `.env` and rebuild the API container.
