# Phase C — Writer + Critic Loop
# Reference Document: Design, Data Flow, Execution, Testing

> Last updated: 2026-03-22
> Status: ✅ COMPLETE (2026-03-24)
> **This was a pre-implementation design doc. See `docs/AGENTIC_DESIGN.md` for the
> authoritative description of the built system.**

---

## What We're Building

Phase C upgrades the Writer from template-filling to context-aware, self-correcting
email generation using the **Reflection** agentic pattern.

| Before Phase C | After Phase C |
|---|---|
| Fill template placeholders | LLM reasons from company context and writes |
| No quality check | Critic scores 0–10 on 5 criteria |
| One shot — whatever comes out is saved | Rewrite loop: up to 2 rewrites if score < 7 |
| Skip company if no contact | Graceful fallback — generic draft with needs_contact flag |
| Approve button does nothing (email not sent) | Approve & Send fires SMTP, logs outreach_event |

---

## Agentic Concepts Used

| Concept | What it means here |
|---|---|
| **Context-Aware Generation** | Writer reads score_reason + company signals, reasons about best angle before writing |
| **Self-Critique / Reflection Loop** | Critic is a separate LLM call that scores the output. Writer sees the score + instruction and rewrites. |
| **Uncertainty Flagging** | If score stays < 7 after 2 rewrites, saved with `low_confidence=true` — agent admits uncertainty |
| **Human-in-the-Loop (HITL)** | Human reviews every draft before it's sent, regardless of critic score |
| **Graceful Degradation** | No contact? Don't skip — write generic draft, flag it |

---

## Where Contact Data Comes From

### Data origin
All contact data is populated by the **Analyst agent** during enrichment, before Writer ever runs.

```
[Scout] saves company (name, website, industry, city, state)
         ↓
[Analyst] enrichment_client.enrich_company()
  → calls Apollo API with company domain
  → Apollo returns: full_name, title, email, linkedin_url
  → saved to contacts table (linked via company_id)
  → also saves: lead_scores (score, tier, score_reason)
                company_features (savings_low/mid/high, site_count, deregulated_state)
         ↓
[Human approves lead] → company.status = "approved"
         ↓
[Writer] reads contacts + lead_scores + company_features → creates draft
```

### Tables involved

**contacts** (populated by Analyst/Apollo)
```
company_id  → FK to companies
full_name   → "Sarah Johnson"
title       → "VP of Operations"
email       → "sjohnson@company.com"
linkedin_url
source      → "apollo"
verified    → true/false
```

**lead_scores** (populated by Analyst Phase A)
```
company_id
score         → 82.5
tier          → "high"
score_reason  → "3-site healthcare org in deregulated NY, high utility spend signal..."
approved_human → true  ← required before Writer runs
```

**company_features** (populated by Analyst)
```
company_id
savings_low / savings_mid / savings_high  → dollar estimates
site_count          → 3
deregulated_state   → true
employee_count      → 450
```

### What if there's no contact?

**Old behavior (Phase B and earlier):** `return None` — company skipped, no draft.

**New behavior (Phase C):**
```
Contact found → personalized email: "Hi Sarah, ..."
                TO: sjohnson@company.com

No contact   → generic email:      "Hi [Company Name] team, ..."
                TO: info@company.com (from website crawl, or left blank)
                draft.needs_contact = true  ← flagged in UI
                Human fills in TO before approving
```

---

## Full Execution Flow

```
─────────────────────────────────────────────────────────────────
  TRIGGER: lead approved (company.status = "approved")
─────────────────────────────────────────────────────────────────
           │
           ▼
┌──────────────────────────────────────────────────────────────┐
│  writer_agent.process_one_company(company_id, db)            │
│                                                              │
│  Step 1 — Load from DB:                                      │
│    companies        → name, industry, city, state, website   │
│    company_features → site_count, savings_mid, savings_high  │
│                       deregulated_state, employee_count      │
│    lead_scores      → score, tier, score_reason  ← KEY       │
│    contacts         → full_name, title, email                │
│                       (fallback: generic if none found)      │
└──────────────────────────────────────────────────────────────┘
           │
           ▼
┌──────────────────────────────────────────────────────────────┐
│  Writer LLM Call  (writer_agent.py / llm_connector.py)       │
│                                                              │
│  Prompt includes:                                            │
│    - company name, industry, city, state                     │
│    - site_count, savings_mid estimate                        │
│    - deregulated_state (yes/no)                              │
│    - score_reason  ← written by Analyst, explains WHY        │
│    - contact first name (or "team" if no contact)            │
│                                                              │
│  Writer reasons first (chain-of-thought):                    │
│    "3-site healthcare org, NY deregulated, score_reason      │
│     says high utility spend → lead with electricity cost     │
│     savings, mention free audit, reference multi-site ops"   │
│                                                              │
│  Then writes: subject_line + body (~150 words)               │
└──────────────────────────────────────────────────────────────┘
           │
           │  draft v1
           ▼
┌──────────────────────────────────────────────────────────────┐
│  Critic Agent  (critic_agent.py)  NEW                        │
│                                                              │
│  Separate LLM call. Evaluates draft on 5 criteria:           │
│    1. Personalized to this company? (not generic boilerplate)│
│    2. Mentions specific savings estimate?                    │
│    3. Has clear CTA / next step?                             │
│    4. Sounds human (not template-like)?                      │
│    5. Subject line specific (not "Quick question")?          │
│                                                              │
│  Returns JSON:                                               │
│    {                                                         │
│      "score": 6,                                             │
│      "passed": false,                                        │
│      "feedback": "Missing savings figure. Subject too        │
│                   generic. Add $180k estimate in para 2."    │
│    }                                                         │
└──────────────────────────────────────────────────────────────┘
           │
     score >= 7?
    /            \
  YES             NO
   │               │
   │         rewrite_count += 1
   │         max rewrites = 2
   │               │
   │         Writer sees original draft + Critic feedback
   │         → generates revised draft
   │         → Critic re-evaluates
   │               │
   │         still < 7 after loop 2?
   │              /          \
   │           YES             NO (passed on rewrite)
   │            │               │
   │     low_confidence=true    │
   │     save anyway            │
   │            │               │
   └────────────┴───────────────┘
                │
                ▼
┌──────────────────────────────────────────────────────────────┐
│  Save to email_drafts table                                  │
│    subject_line    → final subject                           │
│    body            → final body                              │
│    critic_score    → e.g. 8.0  (NEW column)                  │
│    low_confidence  → false / true  (NEW column)              │
│    rewrite_count   → 0, 1, or 2  (NEW column)                │
│    approved_human  → false  (pending human review)           │
│    contact_id      → FK to contacts (or NULL if generic)     │
└──────────────────────────────────────────────────────────────┘
           │
           ▼
────────────────────────────────────────────────────────────────
  HUMAN REVIEW — EmailReview.jsx  (HITL checkpoint)
────────────────────────────────────────────────────────────────
           │
           │  Human sees:
           │    - Critic score badge (8/10 ✓ or 5/10 ⚠)
           │    - LOW CONFIDENCE warning if low_confidence=true
           │    - Rewrite count
           │    - Full draft (editable)
           │    - TO / contact details
           │
           ├── Approve & Send ──────────────────────────────────┐
           ├── Edit + Approve & Send                            │
           ├── Regenerate (new Writer + Critic cycle)           │
           └── Reject                                           │
                                                                │
                                                                ▼
                                              ┌────────────────────────────┐
                                              │  SMTP Send  (emails.py)    │
                                              │    send to contact.email   │
                                              │    or info@company.com     │
                                              └──────────┬─────────────────┘
                                                         │
                                                         ▼
                                              ┌────────────────────────────┐
                                              │  outreach_events row       │
                                              │    event_type = "sent"     │
                                              │    company_id, contact_id  │
                                              │    email_draft_id          │
                                              │    event_at = now          │
                                              └──────────┬─────────────────┘
                                                         │
                                                         ▼
                                              company.status = "contacted"
                                              email_drafts.approved_human = true
```

---

## Files Changed / Created

| File | Change |
|---|---|
| `agents/writer/writer_agent.py` | Remove template-filling, add context-reasoning prompt, call Critic, handle rewrite loop, graceful no-contact fallback |
| `agents/writer/critic_agent.py` | **NEW** — Critic LLM call with 5-criteria rubric, returns `{score, passed, feedback}` |
| `database/orm_models.py` | Add `critic_score` (Float), `low_confidence` (Boolean), `rewrite_count` (Integer) to EmailDraft |
| `database/migrations/` | New Alembic migration for 3 new columns |
| `api/routes/emails.py` | Wire SMTP send on `/emails/{id}/approve`, return new fields in EmailDraftResponse |
| `dashboard/src/pages/EmailReview.jsx` | Add critic score badge, low_confidence warning banner, "Approve & Send" button |

---

## New DB Columns on email_drafts

```sql
ALTER TABLE email_drafts
  ADD COLUMN critic_score     FLOAT,
  ADD COLUMN low_confidence   BOOLEAN DEFAULT false,
  ADD COLUMN rewrite_count    INTEGER DEFAULT 0;
```

---

## Critic Rubric (5 criteria, 2 points each = 10 max)

| Criterion | Pass condition |
|---|---|
| **Personalization** | Mentions company name or a specific company detail |
| **Savings specificity** | Contains a dollar figure or % savings estimate |
| **Clear CTA** | Has a specific next step (call, audit, reply) |
| **Human tone** | Reads like a person wrote it, not a template |
| **Subject line quality** | Specific to company, not generic ("Quick question") |

Score interpretation:
- 8–10: save and send to human queue normally
- 6–7: acceptable, minor issues — still passed
- < 6: trigger rewrite
- < 7 after 2 rewrites: `low_confidence=true`, human gets warning

---

## LLM Calls per Email

| Step | Model calls | ~Tokens |
|---|---|---|
| Writer (initial) | 1 | ~600 |
| Critic (evaluation) | 1 | ~400 |
| Writer (rewrite, if needed) | 0–2 | ~600 each |
| Critic (re-evaluation) | 0–2 | ~400 each |
| **Total worst case** | **6** | **~3,000** |

With Ollama (llama3.2 local): ~15–40s per email worst case.
With OpenAI GPT-4o-mini: ~3–8s per email.

---

## Testing Plan

### Unit tests
```python
# test critic_agent.py
bad_draft = "Hi there, we can save you money. Reply if interested."
result = critic_agent.evaluate(bad_draft, company_context)
assert result["score"] < 7
assert result["passed"] == False
assert "personalization" in result["feedback"].lower()

# test good draft passes
good_draft = "Hi Sarah, given RGH's 3 sites in Monroe County..."
result = critic_agent.evaluate(good_draft, company_context)
assert result["score"] >= 7
```

### Integration tests
```python
# Full Writer + Critic loop
draft_id = writer_agent.process_one_company(approved_company_id, db)
draft = db.get(EmailDraft, draft_id)

assert draft.critic_score is not None       # Critic ran
assert draft.rewrite_count is not None      # Tracked
assert draft.body is not None               # Draft created
assert draft.approved_human == False        # Needs human review
```

### End-to-end (manual)
1. Run full pipeline → approve a lead
2. Trigger Writer via Triggers page or full pipeline
3. Go to Email Review page
4. Confirm: critic_score badge visible, low_confidence warning shows when applicable
5. Click "Approve & Send"
6. Confirm: outreach_events row created with event_type="sent"
7. Confirm: company.status = "contacted"
8. Check inbox (if using real SMTP) or logs (if using test mode)

---

## SMTP Configuration

```env
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your@email.com
SMTP_PASSWORD=app_password_here
SMTP_FROM_NAME=Your Name
SMTP_FROM_EMAIL=your@email.com
SMTP_TEST_MODE=true   # set false to actually send
```

When `SMTP_TEST_MODE=true`: logs the email content, does not send. Safe for development.
When `false`: sends real email via configured SMTP server.

---

## Build Order

1. DB migration (add 3 columns to email_drafts)
2. `critic_agent.py` — standalone, easy to test first
3. Update `writer_agent.py` — add reasoning prompt, Critic call, rewrite loop, no-contact fallback
4. Wire SMTP send in `api/routes/emails.py`
5. Update `EmailReview.jsx` — critic badge + low_confidence warning
6. Test end-to-end
