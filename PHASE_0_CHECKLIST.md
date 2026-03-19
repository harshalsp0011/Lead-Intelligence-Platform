# Phase 0 — Foundation Checklist

## Purpose
Build the database foundation for the agentic system.
Every run, every agent action, every learning signal, and every human approval
must be stored and queryable before any agentic behaviour can work.

---

## Existing Tables (kept as-is)

| Table | Purpose | Changes Needed |
|---|---|---|
| `companies` | stores discovered companies | add `run_id`, `quality_score` columns |
| `directory_sources` | catalog of scrape source URLs | none — used by scout config |
| `company_features` | spend/savings estimates per company | none |
| `lead_scores` | score + tier + human approval per company | none |
| `contacts` | enriched contact records | none |
| `email_drafts` | generated email drafts + human approval | none |
| `outreach_events` | sent/replied/follow-up events | `sales_alerted` repurposed for email (no Slack) |

---

## Phase 0 Steps

### Step 1 — agent_runs table
Track every pipeline run (chat-triggered or Airflow-triggered).
One row per run. Holds target context, current stage, status, counts, errors.

- [x] `008_create_agent_runs.sql` written
- [x] `AgentRun` ORM model added

---

### Step 2 — agent_run_logs table
Step-by-step audit log inside each run.
Every agent action (source tried, quality checked, lead scored, draft created, email sent) logs one row.

- [x] `009_create_agent_run_logs.sql` written
- [x] `AgentRunLog` ORM model added

---

### Step 3 — source_performance table (learning memory)
After every Scout run, write how well each source performed per industry+location.
Next Scout run reads this to pick the best source first.

- [x] `010_create_source_performance.sql` written
- [x] `SourcePerformance` ORM model added

---

### Step 4 — email_win_rate table (learning memory)
After every reply/open event, update win rate per template+industry.
Writer reads this to pick the best-performing template next time.

- [x] `011_create_email_win_rate.sql` written
- [x] `EmailWinRate` ORM model added

---

### Step 5 — human_approval_requests table
Tracks pending human-in-the-loop approvals.
When Analyst finishes or Writer finishes, one row is created.
System sends email notification. Row updated when human approves/rejects.

- [x] `012_create_human_approval_requests.sql` written
- [x] `HumanApprovalRequest` ORM model added

---

### Step 6 — Alter companies table
Add `run_id` (links each company to the run that found it).
Add `quality_score` (raw quality score set by Scout Critic).

- [x] `013_alter_companies_add_run_id.sql` written
- [x] `Company` ORM model updated

---

### Step 7 — ORM models file updated
All new models added to `database/orm_models.py`.

- [x] Done

---

## Remaining (Phase 1 onwards)

- [ ] Chat agent backend (`agents/chat_agent.py`)
- [ ] Chat API route (`POST /chat`)
- [ ] Scout Critic loop (quality evaluation + source retry)
- [ ] Scout source expansion (Google Maps, Yelp)
- [ ] Source performance writeback after each Scout run
- [ ] Email win rate writeback after each reply/open event
- [ ] Human-in-loop pause in Airflow DAG (post-Analyst, post-Writer)
- [ ] Human approval email notification (replace Slack with email)
- [ ] Remove all Slack webhook calls, replace with email
- [ ] Writer Critic loop (quality score + rewrite)
- [ ] Chat UI panel in React dashboard
- [ ] Live Scout visual (companies appearing as found)
- [ ] Pipeline status bar (active stage indicator)
- [ ] Notification center in dashboard (email-based)
- [ ] Full pipeline test: Scout → Analyst → Writer → Outreach → Tracker

---

## Design Decisions

| Decision | Reason |
|---|---|
| No Planner node | Fixed source order, agent adapts via Critic loop |
| No Slack | Email only for all notifications and alerts |
| `source_performance` is separate from `directory_sources` | Sources table = config. Performance table = learning. Different concerns. |
| `human_approval_requests` is separate from `lead_scores`/`email_drafts` | Approval tables track state. Approval requests table tracks notification delivery and queue. |
| Airflow = scheduled add-on, not primary trigger | Chat is primary. Airflow runs on schedule with human-in-loop pauses. |
