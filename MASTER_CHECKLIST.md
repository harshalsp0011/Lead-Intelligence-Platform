# Master Project Checklist
# Utility Lead Intelligence Platform — Agentic System

When every checkbox in this file is checked, the project is complete.
Check items off one by one as they are done.
Never remove a remaining item — mark it done instead.

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
- [ ] On rejection: run cancelled, `agent_runs.status` = `cancelled`
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

## Phase 2.5 — Chat Resilience, Live Progress & UI Fixes
Bugs fixed and reliability improvements after Phase 2 deployment.

### Chat Backend
- [x] `POST /chat` returns `run_id` immediately (background thread) — no more 30s browser timeout
- [x] `GET /chat/result/{run_id}` endpoint added — frontend polls for completion
- [x] `agents/chat_agent.py` — `run_chat()` accepts optional pre-generated `run_id`
- [x] Scout writes human-readable progress to `agent_run_logs` at every phase
- [x] `GET /pipeline/run/{run_id}` returns ALL logs (was capped at 5)

### Chat Frontend
- [x] Chat history persisted to `localStorage` — survives page refresh
- [x] Both user AND agent messages (including data cards) saved and restored
- [x] Active `run_id` persisted to `sessionStorage` — polling resumes if user navigates away mid-run
- [x] On remount: if `sessionStorage` has `chat_active_run_id`, polling resumes immediately
- [x] 404 edge case: if server restarted mid-run, shows "server restarted, try again" instead of polling forever
- [x] Live `ProgressIndicator` replaces generic typing dots — shows `✓` / `→` step-by-step
- [x] "Clear history" button added to Chat header

### Leads Page Fix
- [x] `GET /leads` 500 crash fixed — `_aware()` helper normalizes naive datetimes before sort
- [x] Retry button added to error banner

### Triggers Page
- [x] `ActiveRunStatus` now shows real result summary (companies saved, tiers, drafts) when run completes
- [x] "View in Leads page →" button appears on completion
- [x] Polls every 3s (was 5s)

### Scout Blocklist
- [x] `_UNSCRAPPABLE_DOMAINS` blocklist added to `search_client.py` (27 domains)
- [x] Sites that require login/paywall (glassdoor, zoominfo, seamless.ai, etc.) skipped immediately
- [x] Scout reaches Google Maps/Yelp 60–90 seconds faster

---

## Phase 3 — Writer + Critic Loop + Human-in-Loop (Email Review)
Writer drafts emails. Critic checks quality. Human reviews drafts before Outreach sends.

### 3A — Writer Critic Loop
- [ ] Writer Critic evaluates each draft on a 0–10 quality rubric:
  - [ ] Has savings estimate/number
  - [ ] Personalized to company name and industry
  - [ ] Correct tone (professional, not generic)
  - [ ] Subject line is specific
- [ ] If quality score < 7: Writer rewrites (up to 3 attempts)
- [ ] If score >= 7 after any attempt: draft saved, moves to human review
- [ ] If 3 attempts fail: draft saved with flag `low_confidence = true`
- [ ] All rewrite attempts logged to `agent_run_logs`

### 3B — Writer reads email_win_rate
- [ ] Before generating draft, Writer queries `email_win_rate` for best template per industry
- [ ] If no history: falls back to default template for that industry
- [ ] Template selection logged to `agent_run_logs`

### 3C — Writer connects to run tracking
- [ ] Writer updates `agent_runs.current_stage` to `writer_running`
- [ ] Writer updates `agent_runs.drafts_created` counter
- [ ] Writer updates `agent_runs.status` to `writer_awaiting_approval` when done

### 3D — Human Approval: Emails
- [ ] After Writer finishes, system creates `human_approval_requests` row (`approval_type = 'emails'`)
- [ ] Approval email sent: list of drafts with subject lines, link to email review page
- [ ] `POST /approvals/emails` API route — marks selected drafts as approved
- [ ] On approval: `agent_runs.status` = `writer_complete`, Outreach starts
- [ ] `human_approval_requests` row updated on approval

### 3E — UI: Email Review Page
- [ ] Email review page shows all drafts for current run
- [ ] Each draft shows: subject, body preview, company name, contact name
- [ ] Inline edit for subject line and body
- [ ] "Approve" / "Reject" per draft
- [ ] "Approve All" bulk action
- [ ] `src/pages/EmailReview.jsx` updated

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
| 2 | Analyst + human-in-loop leads review | Not started |
| 3 | Writer critic loop + human-in-loop email review | Not started |
| 4 | Outreach + Tracker + auto email notifications | Not started |
| 5 | Airflow scheduled runs with approval pauses | Not started |
| 6 | Learning activation (source + template selection) | Not started |
| 7 | Full system test | Not started |

---

## Current State (as of Phase 1 complete)

**Both containers are running:**
- Frontend: http://localhost:3000 (nginx serving Vite build)
- API: http://localhost:8001 (FastAPI + Uvicorn)

**What works right now:**
- Chat → Ollama (llama3.2) → responds via `/chat` endpoint
- Chat tools: `search_companies`, `get_leads`, `get_outreach_history`, `get_replies`, `run_full_pipeline`
- Scout Live page: trigger form → `POST /trigger/scout` → polls every 3s for companies
- All 6 dashboard pages render with correct layouts
- API health: `GET /health` returns ok

**What is wired but not yet tested end-to-end:**
- Scout agent actually calling Google Maps / Yelp / Tavily (keys in .env)
- Full pipeline: Scout → Analyst → Writer chain via orchestrator
- Email drafting (Writer agent)

**Next phase to build: Phase 2**
Analyst agent scores companies → human reviews via dashboard → approves before Writer runs.
