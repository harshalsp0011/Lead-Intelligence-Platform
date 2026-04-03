# Build Status — Utility Lead Intelligence Platform

> Last updated: March 2026
> Single source of truth for what is built, what is wired, and what is still missing.
> For agent internals see `agents/<name>/README.md`. For architecture see `docs/SYSTEM_ARCHITECTURE.md`.

---

## Phase Completion

| Phase | What | Status |
|---|---|---|
| Phase 0 | DB schema — agent_runs, agent_run_logs, source_performance, email_win_rate, human_approval_requests | ✅ Complete |
| Phase 1 | Chat agent, Scout expansion (Google Maps + Yelp), live UI, pipeline status bar | ✅ Complete |
| Phase 2 | Analyst scoring, HITL Gate 1 (Leads page), email notifications | ✅ Complete |
| Phase 2.5 | Writer first draft, Email Review page, SendGrid send on approval | ✅ Complete |
| Phase 2.6 | Outreach follow-up sequence (Day 3/7/14), daily cap guardrail | ✅ Complete |
| Phase A | Agentic Analyst — LLM industry inference, data gap detection, re-enrichment loop | ✅ Complete |
| Phase B | Agentic Scout — LLM query planning, multi-source search, LLM dedup, quality retry | ✅ Complete |
| Phase 3 | Agentic Writer — context-aware generation, Critic loop (0–10), rewrite, low_confidence flag | ✅ Complete |

---

## Feature Status

### What Works End-to-End Right Now

```
1. Triggers page → Run Scout
   → LLM plans 3–5 query variants → searches Google Maps + Yelp + Tavily
   → LLM deduplicates → saves companies to DB

2. Triggers page → Run Analyst
   → LLM infers industry + detects data gaps
   → 8-source contact enrichment waterfall
   → Spend + savings calculated → scored 0–100
   → Notification email sent to ALERT_EMAIL with lead list

3. Leads page → review scores → Approve high-tier leads

4. Triggers page → Run Writer
   → LLM picks angle (win-rate biased if ≥5 samples)
   → Draft generated → Critic scores → rewrite if <7 (max 2)
   → low_confidence flag set if never reaches 7
   → Notification email sent with draft list

5. Email Review page → read each draft → Approve & Send
   → Email sent via SendGrid → follow-ups scheduled (Day 3/7/14)

6. Outreach scheduler → sends follow-ups as they come due
   → Sequence complete after Day 14 → company.status = no_response
```

---

## What Is Built

| Feature | Status | Notes |
|---|---|---|
| Scout — LLM query planning | ✅ Built | 3–5 variants per run, quality retry if <80% target |
| Scout — multi-source search | ✅ Built | Google Maps + Yelp + Tavily + directory scraper |
| Scout — LLM deduplication | ✅ Built | Domain match + LLM near-duplicate name review |
| Scout — source performance learning | ✅ Built | Writes quality scores to source_performance |
| Analyst — LLM inspector | ✅ Built | Industry inference, data gap detection, re-enrichment |
| Analyst — contact enrichment waterfall | ✅ Built | 8 sources: Hunter → Apollo → scraper → Serper → Snov → Prospeo → ZeroBounce → permutation. Verified-only save gate: unverified emails discarded (generic_inbox excepted) |
| Analyst — spend + savings calc | ✅ Built | Deterministic: industry_benchmarks.json × state rate |
| Analyst — score formula | ✅ Built | `(Recovery×0.40) + (Industry×0.25) + (Multisite×0.20) + (DataQuality×0.15)` |
| Writer — context-aware generation | ✅ Built | LLM reasons about angle before writing, no static templates |
| Writer — Critic loop | ✅ Built | 5-criterion rubric, rewrite if <7.0, max 2 rewrites |
| Writer — win-rate angle selection | ✅ Built | Reads email_win_rate, injects hint if ≥5 samples |
| Writer — low_confidence flag | ✅ Built | Set when draft never reaches 7.0 after all rewrites |
| HITL Gate 1 — Leads page | ✅ Built | Approve/reject per lead, notification email |
| HITL Gate 2 — Email Review page | ✅ Built | Approve/Edit/Reject/Regenerate, notification email |
| Outreach — first email send | ✅ Built | SendGrid + Instantly, unsubscribe guard, daily cap |
| Outreach — follow-up sequence | ✅ Built | Day 3/7/14, LLM-polished body, subject "Re:" / "Following up one last time" |
| Tracker — webhook receiver | ✅ Built | FastAPI on port 8002, HMAC validation, parses open/click/bounce/unsubscribe/reply |
| Tracker — reply classification | ✅ Built | LLM-first + rule-based fallback (wants_meeting / wants_info / unsubscribe / not_interested) |
| Tracker — sales alert | ✅ Built | Email to ALERT_EMAIL on positive reply, dashboard deep-link |
| Tracker — unsubscribe/bounce handling | ✅ Built | contact.unsubscribed, cancel follow-ups, archive if no active contacts |
| Tracker — daily health checks | ✅ Built | Detects stuck leads (5-day stale), sends approval reminders |
| Orchestrator — full pipeline run | ✅ Built | run_full_pipeline() → Scout → Analyst → enrich → Writer |
| Orchestrator — task retry | ✅ Built | 2-pass retry per agent, logs to task_log.txt |
| Orchestrator — pipeline monitor | ✅ Built | Stage counts, value rollup, health checks, stuck detection |
| Orchestrator — weekly report | ✅ Built | Discovery + scoring + email + reply metrics |
| Chat agent | ✅ Built | LangChain ReAct, 3-tier routing, multi-turn context, background-thread (non-blocking), localStorage history |
| Dashboard — Leads, Pipeline, Triggers, Email Review | ✅ Built | — |

---

## What Is Built But Not Fully Wired

| Feature | What Exists | What's Missing |
|---|---|---|
| Tracker `process_event()` routing | Webhook receives and parses events; `status_updater`, `reply_classifier`, `alert_sender` all built | Full routing inside `process_event()` — each event type not yet dispatched to the right handler |
| Win-rate feedback loop | `email_win_rate` table, Writer reads it, Tracker handlers written | Tracker doesn't write to `email_win_rate` yet (needs `process_event` wiring) |
| Airflow scheduling | DAGs exist | Airflow not running as a live scheduled service — follow-ups and daily checks must be triggered manually |

---

## In Planning

| Feature | Plan Doc | Status |
|---|---|---|
| CRM Leads Email Flow — new tab on Email Review + CRM writer path + context storage | `docs/CRM_LEADS_EMAIL_PLAN.md` | Planned — not started |

---

## What Is Not Built

### Reply Detection via CRM
After send, the platform has no way to receive replies coming through a CRM (e.g., deal stage change, meeting booked via CRM calendar).

**To build:**
- `POST /api/webhooks/crm/reply` — CRM fires on inbound reply → match contact → log reply event → cancel follow-ups → set status=replied → alert sales
- `POST /api/webhooks/crm/meeting` — CRM fires on meeting booked → set status=meeting_booked → cancel follow-ups

### CRM Push Sync
After email is sent, company/contact/deal not pushed to CRM. Sales team has no CRM view.

**To build:**
- After `send_email()` succeeds → create Contact + Deal in CRM via CRM REST API
- On status change (replied → meeting_booked → won) → update CRM deal stage
- Platform is CRM-agnostic — same pattern for any CRM with REST API + webhooks

### CRM Import
No way to pull existing contacts from a CRM into the platform.

**To build:**
- "Import from CRM" on Leads page → fetch contacts from CRM Contacts API → map to companies/contacts tables → enter scoring pipeline

### Manual Lead Add
No form to add a company manually.

**To build:**
- Form: company name, website, industry, state, contact name, email, title
- Creates company + contact rows with `source="manual"`

### Dashboard — Reply Inbox
No page to view and manage received replies.

**To build:** `src/pages/Replies.jsx` — list replies with company, contact, reply text, sentiment, date, link to company detail

### Dashboard — Company Timeline
No full history view per company.

**To build:** Timeline on Lead Detail page — discovered → scored → approved → emailed → opened → replied → meeting booked

### Dashboard — Notification Center
No in-app alerts for replies, failures, or approvals needed.

**To build:** `src/components/NotificationCenter.jsx` — badge count on nav, click navigates to relevant page

---

## What Is Deferred

| Feature | Reason |
|---|---|
| Bulk approve all emails in Email Review | Low priority — individual approval preferred for quality control |
| Phase D: Chat dynamic filter combinations | Chat already handles most cases via 3-tier routing |
| SerpAPI as Scout news source | Enhancement — Scout works well with current sources |

---

## Build Priority

```
1. Tracker process_event() full wiring     ← closes the reply detection gap cheaply (code exists)
   → connects webhook → classifier → status_updater → alert_sender

2. Win-rate writeback                      ← activates learning loop (needs #1 first)
   → Tracker writes email_win_rate on reply events

3. Reply detection — CRM webhook           ← closes biggest pipeline gap
   POST /api/webhooks/crm/reply + /meeting

4. CRM push sync                           ← gives sales team CRM visibility
   → create deal after send, update on status change

5. Manual lead add + CRM import            ← unlocks existing contacts as source

6. Airflow live scheduling                 ← makes follow-ups and daily checks automatic

7. Reply inbox page                        ← makes replies visible in dashboard

8. Notification center                     ← ties all alerts together in-app

9. Company timeline                        ← full audit trail per company
```

---

## Key File Locations

| Feature | File |
|---|---|
| Scout | `agents/scout/scout_agent.py` |
| Analyst | `agents/analyst/analyst_agent.py` |
| Enrichment | `agents/analyst/enrichment_client.py` |
| Writer | `agents/writer/writer_agent.py` |
| Critic | `agents/writer/critic_agent.py` |
| Outreach send | `agents/outreach/email_sender.py` |
| Follow-up scheduling | `agents/outreach/followup_scheduler.py` |
| Follow-up content | `agents/outreach/sequence_manager.py` |
| Tracker webhook | `agents/tracker/webhook_listener.py` |
| Tracker reply classifier | `agents/tracker/reply_classifier.py` |
| Tracker status updates | `agents/tracker/status_updater.py` |
| Tracker sales alerts | `agents/tracker/alert_sender.py` |
| Orchestrator | `agents/orchestrator/orchestrator.py` |
| Pipeline monitor | `agents/orchestrator/pipeline_monitor.py` |
| Chat agent | `agents/chat_agent.py` |
| Airflow DAGs | `dags/` |
| API routes | `api/routes/` |
| DB models | `database/orm_models.py` |
| DB migrations | `database/migrations/` |
| Industry benchmarks | `database/seed_data/industry_benchmarks.json` |
| Settings | `config/settings.py`, `.env` |
