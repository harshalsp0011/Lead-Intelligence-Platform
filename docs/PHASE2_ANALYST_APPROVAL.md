# Phase 2 — Analyst Scoring + Human-in-Loop Lead Review

## What Was Built

Phase 2 adds the scoring layer between Scout and Writer, plus a human review
checkpoint so no lead goes to the Writer stage without someone approving it first.

---

## Components Built

| Component | File | Purpose |
|---|---|---|
| Analyst run tracking | `agents/analyst/analyst_agent.py` | Logs each score to DB, updates run status |
| Email notifier | `agents/notifications/email_notifier.py` | Sends SendGrid emails for approvals and alerts |
| Approval API route | `api/routes/approvals.py` | `POST /approvals/leads` — bulk approve/reject |
| Approval router registered | `api/main.py` | Mounted at `/approvals` prefix |
| Leads UI field fix | `dashboard/src/pages/Leads.jsx` | Fixed field names to match API response schema |
| Chat tool: approve_leads | `agents/chat_agent.py` | Lets user approve leads by typing in chat |
| Orchestrator notification | `agents/orchestrator/orchestrator.py` | Creates approval request + sends email post-scoring |
| Pipeline log fix | `api/routes/pipeline.py` | Fixed `AgentRunLog.created_at` → `logged_at` bug |

---

## What the Analyst Does

The Analyst scores every company that Scout found on a **0–100 scale** using 4 weighted factors:

```
Score = (Recovery × 0.40) + (Industry × 0.25) + (Multisite × 0.20) + (Data Quality × 0.15)
```

### Recovery (savings estimate)
How much money Troy & Banks can recover for the client. Calculated from:
- Estimated utility spend (site count × industry benchmark)
- Estimated telecom spend (employee count × industry benchmark)
- T&B's 24% contingency fee applied to estimated total spend

| Savings Range | Recovery Score |
|---|---|
| ≥ $2M | 100 pts |
| ≥ $1M | 85 pts |
| ≥ $500k | 70 pts |
| ≥ $250k | 55 pts |
| < $250k | 40 pts |

### Industry fit
| Industry | Score |
|---|---|
| Healthcare, Hospitality, Manufacturing, Retail | 90 pts |
| Public Sector, Office | 70 pts |
| Other | 55 pts |

### Multisite (more sites = more spend to recover)
| Sites | Score |
|---|---|
| 20+ | 20 pts |
| 10–19 | 17 pts |
| 5–9 | 13 pts |
| 2–4 | 8 pts |
| 1 | 3 pts |

### Data quality (how complete the company record is)
Each signal present adds 2 pts (max 10): website, locations page, site count, employee count, contact found.

### Tier assignment
| Score | Tier |
|---|---|
| ≥ 70 | **high** |
| 40–69 | **medium** |
| < 40 | **low** |

Saved to `lead_scores` table. Writer only drafts emails for **high + approved** companies.

---

## How the Full Flow Works (Phase 2)

```
User: "find 10 healthcare companies in Buffalo NY"
          │
          ▼
    Chat agent calls search_companies tool
          │
          ▼
    Scout runs (4 sources: directory → Tavily → Google Maps → Yelp)
    Saves companies to DB with status = "new"
          │
          ▼
    [Optional] User: "run the analyst"
    OR trigger via: POST /trigger/analyst
          │
          ▼
    Analyst runs for each company:
      1. Crawl website (if site_count = 0)
      2. Calculate utility + telecom spend estimates
      3. Compute 0–100 score
      4. Assign tier (high/medium/low)
      5. Save to lead_scores + company_features tables
      6. Update company.status = "scored"
      7. Log each action to agent_run_logs
      8. Update agent_runs.companies_scored counter
          │
          ▼
    After all companies scored:
      - agent_runs.status = "analyst_awaiting_approval"
      - HumanApprovalRequest row created in DB
      - SendGrid email sent to ALERT_EMAIL
          │
          ▼ (email arrives)
    Reviewer opens: http://localhost:3000/leads
    Sees table: name | industry | city | score | tier | savings
    Clicks "Approve" on high-tier leads, "Reject" on others
          │
     OR: via chat: "approve company <UUID>"
     OR: via API: POST /approvals/leads
          │
          ▼
    Approved leads: lead_scores.approved_human = true, status = "approved"
    Rejected leads: status = "archived"
    agent_runs.status = "analyst_complete"
    human_approval_requests row updated with approved_by + approved_at
          │
          ▼
    Pipeline continues → Writer stage (Phase 3)
```

---

## Where to See It

### 1. Leads Page (primary UI)
**URL:** `http://localhost:3000/leads`

The Leads page shows every company that has been scored.

| Column | What it shows |
|---|---|
| Company | Name (clickable → detail page) |
| Industry | Industry category |
| State | US state abbreviation |
| Sites | Estimated number of locations |
| Annual Spend | Estimated total utility + telecom spend |
| Est. Savings | Mid-point savings estimate (Troy & Banks recovery) |
| Score | 0–100 numeric score + blue progress bar |
| Tier | Green=high / Yellow=medium / Gray=low badge |
| Status | new → scored → approved → contacted → replied → won |
| Contact | ✓ if a contact email was found for this company |
| Actions | View / Approve (high only) / Reject |

**Bulk approve:** Check the checkbox on multiple rows → "Approve N High Leads" button appears at top.

**Filter:** Industry dropdown, State text field, Tier dropdown, Status dropdown, Min Score slider, Name search.

### 2. Chat Agent (approve by voice)
**URL:** `http://localhost:3000/chat`

Type: `"approve company <paste UUID here>"`
Or: `"approve these leads: uuid1, uuid2, uuid3"`

The `approve_leads` tool handles it — no need to go to the Leads page.

### 3. API (direct programmatic approval)
**URL:** `POST http://localhost:8001/approvals/leads`

```json
{
  "run_id": "uuid-of-the-agent-run",
  "approved_company_ids": ["uuid1", "uuid2"],
  "rejected_company_ids": ["uuid3"],
  "approved_by": "john"
}
```

Response:
```json
{
  "success": true,
  "approved_count": 2,
  "rejected_count": 1,
  "run_status": "analyst_complete",
  "message": "Approved 2 leads. Pipeline continues to Writer stage."
}
```

See pending approvals: `GET http://localhost:8001/approvals/leads`

### 4. Swagger UI (test all endpoints)
**URL:** `http://localhost:8001/docs`

Find `/approvals/leads` in the list. Click "Try it out" to test without writing code.

### 5. Database (raw audit)
```sql
-- See all scored leads
SELECT c.name, ls.score, ls.tier, ls.approved_human, ls.approved_by
FROM companies c
JOIN lead_scores ls ON ls.company_id = c.id
ORDER BY ls.score DESC;

-- See pending approval requests
SELECT id, run_id, items_count, items_summary, notification_sent, created_at
FROM human_approval_requests
WHERE status = 'pending';

-- See analyst run logs
SELECT agent, action, status, output_summary, duration_ms
FROM agent_run_logs
WHERE agent = 'analyst'
ORDER BY logged_at DESC LIMIT 20;

-- See run progress
SELECT id, status, current_stage, companies_found, companies_scored, companies_approved
FROM agent_runs
ORDER BY created_at DESC LIMIT 5;
```

### 6. LangSmith (trace the analyst run)
Every analyst scoring pass triggered from chat shows up in LangSmith as a trace.
Login at `https://smith.langchain.com` → project `utility-lead-platform` → find the run by timestamp.

---

## Email Notifications

When Analyst finishes, a SendGrid email is sent to `ALERT_EMAIL` (configured in `.env`).

**Subject:** `[Troy & Banks] N High-Tier Leads Ready for Review`

**Body contains:**
- Run ID
- Count of high / medium leads
- Table of top 20 companies with score, tier, savings estimate
- Button linking to `http://localhost:3000/leads`

The email is also sent for:
- Reply received from a prospect: `send_reply_alert()`
- Pipeline run completion: `send_pipeline_summary()`

If `SENDGRID_API_KEY` is not set, the notification is skipped and a warning is logged
(platform still works, just no email).

---

## Files Changed in Phase 2

```
agents/
  analyst/
    analyst_agent.py          ← Added run tracking (run_id param, agent_run_logs writes)
  notifications/
    __init__.py               ← New package
    email_notifier.py         ← New: SendGrid email sender for approvals + alerts
  orchestrator/
    orchestrator.py           ← Added: HumanApprovalRequest creation + notification after scoring
  chat_agent.py               ← Added: approve_leads tool + system prompt update

api/
  routes/
    approvals.py              ← New: POST /approvals/leads, GET /approvals/leads
    pipeline.py               ← Bugfix: AgentRunLog.logged_at (was .created_at)
  main.py                     ← Registered approvals router

dashboard/src/pages/
  Leads.jsx                   ← Fixed field names: company_id, score, site_count, savings_mid
```

---

## What Comes Next — Phase 3

Writer agent:
- Reads `email_win_rate` table to pick best template per industry
- Generates email draft for each approved high-tier company
- Writer Critic scores draft quality 0–10 (savings number? personalized? correct tone?)
- If score < 7: rewrites (up to 3 attempts)
- Human reviews drafts on Email Review page before any email is sent
- `POST /approvals/emails` → marks drafts approved → Outreach sends them
