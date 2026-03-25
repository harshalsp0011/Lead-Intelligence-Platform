# Utility Lead Intelligence Platform

AI-assisted B2B prospecting and outreach system for the **Troy & Banks** sales team.
The primary interface is a **conversational chatbot** — the sales team types natural language,
the agent decides what to do, and results appear inline as cards.

---

## Table of Contents

1. [What It Does](#1-what-it-does)
2. [Architecture](#2-architecture)
3. [Agent System](#3-agent-system)
4. [Tech Stack](#4-tech-stack)
5. [Project Status](#5-project-status)
6. [Quick Start](#6-quick-start)
7. [Configuration Reference](#7-configuration-reference)
8. [Dashboard Pages](#8-dashboard-pages)
9. [Observability & Monitoring](#9-observability--monitoring)
10. [Database Tables](#10-database-tables)
11. [API Reference](#11-api-reference)
12. [Troubleshooting](#12-troubleshooting)

---

## 1. What It Does

The platform automates the full sales prospecting cycle for Troy & Banks:

```
Find companies  →  Score as leads  →  Draft outreach emails
→  Send with follow-ups  →  Track replies  →  Alert sales team
```

Every step can be triggered by typing in the chat:
- `"find 10 healthcare companies in Buffalo NY"` — Scout runs, companies appear live
- `"show me all high-tier leads"` — queries the database, renders lead cards
- `"run the full pipeline for manufacturing in Chicago"` — Scout + Analyst + Writer chain
- `"who replied to our emails?"` — shows reply list with sentiment

Human approval checkpoints exist after scoring (before emails are drafted) and after drafting
(before emails are sent). No email goes out without a human reviewing it first.

---

## 2. Architecture

### Full System Flow

```
┌─────────────────────────────────────────────────────────┐
│                    Browser (localhost:3000)               │
│                  React + Vite + Tailwind                  │
│                                                          │
│  Chat Page  │  Scout Live  │  Leads  │  Emails  │  etc. │
└─────────────────────────┬───────────────────────────────┘
                          │  HTTP (fetch)
                          ▼
┌─────────────────────────────────────────────────────────┐
│                   API Layer (localhost:8001)              │
│                    FastAPI + Uvicorn                      │
│                                                          │
│  POST /chat   GET /leads   GET /emails   POST /trigger   │
│  GET /pipeline/status      GET /reports/weekly           │
└──────┬───────────────┬──────────────────────────────────┘
       │               │
       ▼               ▼
┌──────────────┐  ┌────────────────────────────────────────┐
│  Chat Agent  │  │          Other API Routes               │
│              │  │  (leads, emails, pipeline, reports,     │
│  LangChain   │  │   triggers — direct DB queries)         │
│  create_agent│  └──────────────────────┬─────────────────┘
│  + tools     │                         │
└──────┬───────┘                         │
       │ picks tool                      │
       ▼                                 ▼
┌──────────────────────────────────────────────────────────┐
│                       Agents                              │
│                                                          │
│  Scout Agent         Analyst Agent    Writer Agent        │
│  (4 sources)         (score + tier)   (draft emails)      │
│                                                          │
│  Outreach Agent      Tracker Agent                        │
│  (send + followup)   (reply monitor + alert)              │
└──────┬──────────────────────────────────────┬────────────┘
       │                                      │
       ▼                                      ▼
┌─────────────────────┐         ┌─────────────────────────┐
│   External APIs      │         │   PostgreSQL (AWS RDS)   │
│                      │         │                         │
│  Tavily (search)     │         │  companies              │
│  Google Maps Places  │         │  lead_scores            │
│  Yelp Business       │         │  contacts               │
│  ScraperAPI (proxy)  │         │  email_drafts           │
│  Hunter.io (enrich)  │         │  outreach_events        │
│  SendGrid (email)    │         │  agent_runs             │
│  Ollama (LLM local)  │         │  agent_run_logs         │
│  OpenAI (optional)   │         │  source_performance     │
└─────────────────────┘         │  email_win_rate         │
                                 │  human_approval_requests│
                                 └─────────────────────────┘
```

### Docker Services (what actually runs)

```
docker-compose up
  ├── api       (port 8001)  FastAPI backend — all agents run inside this process
  └── frontend  (port 3000)  nginx serving the Vite-built React app
```

No separate agent containers. No Airflow container in the default setup.
Airflow is a Phase 5 add-on for scheduled runs, not required for chat-driven operation.
Database is external AWS RDS — not in Docker.

### Human-in-Loop Checkpoints

```
Scout finds companies
        │
        ▼
  [HUMAN REVIEW]  ← approve/reject leads on dashboard  (Phase 2)
        │
        ▼
Analyst scores approved companies
        │
        ▼
  [HUMAN REVIEW]  ← approve/reject email drafts on dashboard  (Phase 3)
        │
        ▼
Outreach sends approved emails
        │
        ▼
Tracker monitors replies → auto email alert to sales team  (Phase 4)
```

---

## 3. Agent System

### Agentic Design Principle

```
Automation (old):   User → fixed code → fixed query → fixed formula → result

Agentic (current):  User → LLM reasons about intent
                         → decides what tools to call and in what order
                         → executes tools (APIs, DB, math)
                         → evaluates result quality
                         → loops if not good enough
                         → returns result
```

**LLM = decision and reasoning layer only.**
**APIs / DB / math = deterministic tools it calls.**
LLM never does math. LLM never calls APIs directly. LLM classifies, infers, decides, evaluates, generates text.

---

### How the Chat Agent Decides What To Do

The chat agent uses LangChain's `create_agent` with a **system prompt** and tools.
Three-tier routing decides how to handle each message:

```
Tier 1 — Conversational:  greetings, small talk → direct LLM reply, no tools called
Tier 2 — Intent parser:   simple data queries → Python extracts filters, calls tool directly
Tier 3 — Agent loop:      complex/multi-step → full LangChain ReAct with tools

User: "how many schools do we have right now?"
  ↓
LLM reasons:
  "schools" → industry = education
  "right now" → current DB count
  "how many" → count query
  ↓
Calls: get_leads(industry="education")
  ↓
Returns: "You have 14 education companies — 3 high, 8 medium, 3 low tier"
```

LLM builds filter parameters dynamically from conversation context — not hardcoded route matching.

### Chat Agent Tools

| Tool | Triggered when user says | What runs |
|---|---|---|
| `search_companies` | "find companies", "search for", "discover" | Scout agent → 4 external sources |
| `get_leads` | "show leads", "high-tier leads", "scored" | SQL: companies JOIN lead_scores |
| `get_outreach_history` | "who did we email", "already contacted" | SQL: outreach_events WHERE type=sent |
| `get_replies` | "any replies", "who replied", "interested" | SQL: outreach_events WHERE type=replied |
| `run_full_pipeline` | "run full pipeline", "start everything" | Scout → Analyst → Writer chain |
| `approve_leads` | "approve these leads", "approve company X" | Updates lead_scores.approved_human=True, status=approved |

---

### Scout Agent — Agentic Company Discovery (Phase B)

**Current (rule-based):** one fixed query per source, e.g. `"healthcare in Buffalo NY"`

**Being upgraded to (Phase B):** LLM Query Planner generates multiple variants, runs them all, deduplicates, checks quality, and retries if target not met.

```
User: "find schools in Buffalo"
  ↓
LLM Query Planner generates:
  ["elementary schools Buffalo NY", "private schools Western New York",
   "K-12 school districts Erie County", "universities Buffalo NY"]
  ↓
Run ALL queries in parallel across Google Maps + Tavily
  ↓
LLM Deduplicator: merges near-duplicate results
  ↓
LLM Quality Check: "found 12, target 20 — generate 3 more queries or accept?"
  ↓
Save companies to DB
```

Current sources (still used, just with smarter queries):
```
1. Directory Scraper  — configured sources in DB (Yellow Pages, local dirs)
2. Tavily             — AI-powered web search
3. Google Maps        — Places API
4. Yelp               — Business Search API
```

---

### Analyst Agent — Agentic Scoring (Phase A)

**Current (rule-based):** exact string match for industry, silently uses 0 for missing data, template score reason.

**Being upgraded to (Phase A):** LLM reasons about available data, infers missing values, decides whether to re-enrich before scoring, generates narrative score reason.

```
Load company from DB
  ↓
LLM Data Inspector:
  "industry=unknown but name says 'Surgical Associates' → healthcare"
  "employee_count=0, site_count=0 → need more data before scoring"
  → action: enrich_before_scoring
  ↓
Re-enrichment loop (if needed): crawl → Apollo → Hunter
  ↓
score_engine.compute_score(...)   ← math stays deterministic
  ↓
LLM Score Narrator:
  "250-employee healthcare company, 3 sites in deregulated NY —
   strong audit candidate with ~$180k annual savings potential"
```

Score formula (unchanged — deterministic):
```
Score = (Recovery × 0.40) + (Industry × 0.25) + (Multisite × 0.20) + (Data Quality × 0.15)
```

Tier: **≥70 = high**, **40–69 = medium**, **<40 = low**

---

### Writer Agent — Agentic Draft Generation ✅ Complete (Phase 3)

```
Writer: queries email_win_rate for best angle → reads company data + score_reason
  → reasons about which angle fits this company → generates full email (subject + body + ANGLE)
  ↓
Critic: evaluates 0–10 (personalised? specific number? clear CTA? sounds human? subject specific?)
  → score=6, feedback="no savings figure", instruction="add $180k estimate in paragraph 2"
  ↓
If score < 7: Writer rewrites using Critic feedback → re-evaluate (max 2 rewrites)
If score ≥ 7: save draft → human review queue
If still < 7 after 2 rewrites: save with low_confidence=true → flagged in UI

Angle chosen (e.g. "audit_offer") saved as template_used → Tracker updates email_win_rate on reply
→ next Writer run reads it and biases toward winning angle for this industry
```

---

### Agent Learning Tables

| Table | What it tracks | Who writes it | Who reads it |
|---|---|---|---|
| `source_performance` | Quality score per source per industry/location | Scout after each run | Scout at next run (ranks sources best-first) |
| `email_win_rate` | Open/reply rate per angle per industry | Tracker after reply events | Writer before drafting (picks best angle) |

### Run Tracking

Every chat message or pipeline trigger creates one `agent_runs` row:

```
agent_runs
  id, trigger_source ("chat" / "airflow"), status, current_stage
  companies_found, companies_scored, drafts_created, emails_sent
  started_at, completed_at, error_message
```

Every tool call appends one `agent_run_logs` row — full audit trail of every action.

---

## 4. Tech Stack

| Layer | Technology | Purpose |
|---|---|---|
| Frontend | React 18 + Vite + Tailwind CSS | Dashboard UI |
| Routing | React Router v6 | Page navigation |
| API | FastAPI + Uvicorn | REST backend, agent orchestration |
| Agent framework | LangChain 1.x `create_agent` | LLM tool-calling loop |
| LLM (local) | Ollama + llama3.2 | Default — runs on your machine |
| LLM (cloud) | OpenAI gpt-4o-mini | Optional — set `LLM_PROVIDER=openai` |
| ORM | SQLAlchemy | Database models and queries |
| Database | PostgreSQL on AWS RDS | External — not in Docker |
| Scraping proxy | ScraperAPI | Directory scraping |
| Search | Tavily API | Company discovery fallback |
| Maps | Google Maps Places API | Company discovery source |
| Business search | Yelp Business API | Company discovery source |
| Enrichment | Hunter.io | Contact email finder |
| Email delivery | SendGrid | Outreach sending |
| Containerization | Docker + nginx | 2 containers: api + frontend |
| Scheduled runs | Airflow (Phase 5) | Add-on, not default |

---

## 5. Project Status

| Phase | Description | Status |
|---|---|---|
| **0** | Database schema — run tracking, learning, approval tables | ✅ Complete |
| **1** | Chat agent + Scout (4 sources) + full React dashboard + Docker | ✅ Complete |
| **2** | Analyst scoring + human lead review + approval notifications | ✅ Complete |
| **2.5** | Chat resilience, live progress, UI fixes, chat intelligence | ✅ Complete |
| **2.6** | Contact enrichment hardening — waterfall, Prospeo, ZeroBounce, quality gates | ✅ Complete |
| **3** | Writer + Critic loop + win rate learning + run tracking + email approval notification | ✅ Complete |
| **A** | Agentic Analyst — LLM industry inference, data gap loop, score narration | 🔲 Next |
| **B** | Agentic Scout — LLM query planning, deduplication, quality loop | 🔲 Next |
| **4** | Outreach sending + Tracker + auto reply email alerts | 🔲 Planned |
| **5** | Airflow scheduled runs with approval pause points | 🔲 Planned |
| **6** | Learning activation (source ranking + angle selection) | 🔲 Planned |
| **7** | Full end-to-end system test | 🔲 Planned |

See `MASTER_CHECKLIST.md` for detailed item-by-item progress.
See `AGENTIC_TRANSFORMATION_PLAN.md` for the full agentic reasoning design.

**What works right now:**
- Chat → Ollama → 3-tier routing → DB queries or Scout run
- Chat: `"show me healthcare leads"` → correct filtered results
- Chat: `"approve these leads"` → marks leads approved in DB
- Scout Live page — trigger a search, watch companies appear in real time
- Leads page — filter/review/approve leads with correct score + savings
- Analyst scoring — runs after Scout, scores 0–100, tiers, narrative score reason
- Analyst: Apollo fallback for `employee_count` enrichment when crawl fails
- Contact enrichment — 8-step waterfall (Hunter → Apollo → scraper → Serper → Snov → Prospeo → ZeroBounce → permutation → generic fallback)
- Phone enrichment — Google Places → Yelp → website scraper
- Triggers page — per-company live progress, results stay after completion
- Writer — context-aware LLM generation, Critic loop (max 2 rewrites), `low_confidence` flag
- Writer reads `email_win_rate` for best angle per industry (learning layer)
- Writer run tracking — `AgentRun` row with live `drafts_created` counter
- Approval email (leads) — SendGrid notification after Analyst finishes
- Approval email (drafts) — SendGrid notification after Writer finishes, lists all drafts with AI scores
- Email Review page — approve / edit+approve / reject / regenerate per draft
- Reject → company resets to `approved`, re-appears in Generate Drafts queue

**What is NOT agentic yet (being upgraded in Phases A + B):**

| Agent | Current behavior | Agentic upgrade |
|---|---|---|
| Analyst | exact string match for industry, silently uses 0 for missing data | Phase A: LLM infers industry, detects gaps, re-enriches |
| Scout | one fixed query per source | Phase B: LLM generates query variants, parallel, quality loop |

---

## 6. Quick Start

### Prerequisites

- Docker Desktop running
- Ollama installed and running locally with llama3.2 pulled
- AWS RDS PostgreSQL instance (or any PostgreSQL) with migrations applied

```bash
# Check prerequisites
docker --version
ollama list       # should show llama3.2
```

### Setup

```bash
# 1. Clone
git clone <your-repo-url>
cd utility-lead-platform

# 2. Copy env file
cp .env.example .env
# Fill in: DATABASE_URL, TAVILY_API_KEY, HUNTER_API_KEY,
#          SENDGRID_API_KEY, SENDGRID_FROM_EMAIL, ALERT_EMAIL
# Optional: GOOGLE_MAPS_API_KEY, YELP_API_KEY

# 3. Pull Ollama model (runs on your host machine)
ollama pull llama3.2

# 4. Run database migrations (run once against your PostgreSQL)
psql $DATABASE_URL -f database/migrations/001_create_companies.sql
psql $DATABASE_URL -f database/migrations/002_create_contacts.sql
# ... run all migrations in order 001–016

# 5. Build and start containers
docker-compose up --build
```

### Or using docker-compose

```bash
docker-compose up --build
```

### Access

| Service | URL |
|---|---|
| Dashboard | http://localhost:3000 |
| API | http://localhost:8001 |
| API docs (Swagger) | http://localhost:8001/docs |

### First conversation

Open http://localhost:3000 → Chat Agent tab → type:

```
find 10 healthcare companies in Buffalo NY
```

The agent will call Scout, which searches Tavily / Google Maps / Yelp,
saves companies to the database, and shows them as cards in the chat.

### Useful container commands

```bash
# View API logs (see tool calls, errors)
docker-compose logs api -f

# Rebuild and restart API after code changes
docker-compose build api && docker-compose up -d api

# Rebuild and restart frontend after UI changes
docker-compose build frontend && docker-compose up -d frontend

# Stop everything
docker-compose down
```

---

## 7. Configuration Reference

All config is read from `.env`. Copy `.env.example` to `.env` and fill in values.

### Required

| Variable | Description | Example |
|---|---|---|
| `DATABASE_URL` | PostgreSQL connection string (AWS RDS or local) | `postgresql://user:pass@host:5432/dbname` |
| `LLM_PROVIDER` | `ollama` (local) or `openai` (cloud) | `ollama` |
| `LLM_MODEL` | Model name for selected provider | `llama3.2` |
| `OLLAMA_BASE_URL` | Ollama server URL (Docker uses host.docker.internal) | `http://host.docker.internal:11434` |
| `TAVILY_API_KEY` | Tavily search API key | `tvly-...` |
| `SCRAPERAPI_KEY` | ScraperAPI key for directory scraping | `abc123...` |
| `HUNTER_API_KEY` | Hunter.io — domain email search (50/month) | `abc123...` |
| `SENDGRID_API_KEY` | SendGrid email delivery key | `SG.xxx` |
| `SENDGRID_FROM_EMAIL` | Verified sender email address | `team@company.com` |
| `ALERT_EMAIL` | Email address for all notifications (no Slack) | `sales@company.com` |
| `TB_BRAND_NAME` | Brand name in email footers | `Troy & Banks` |
| `TB_SENDER_NAME` | Sender name in outbound emails | `John Smith` |
| `TB_SENDER_TITLE` | Sender title in outbound emails | `Intern` |

### Optional

| Variable | Description | Default |
|---|---|---|
| `OPENAI_API_KEY` | Required only if `LLM_PROVIDER=openai` | blank |
| `GOOGLE_MAPS_API_KEY` | Google Places — company discovery + phone lookup | blank |
| `YELP_API_KEY` | Yelp Business — company discovery + phone fallback | blank |
| `SERPER_API_KEY` | Serper.dev — Google search for email discovery (2,500/month) | blank |
| `SERPAPI_API_KEY` | SerpAPI — Google search fallback (100/month) | blank |
| `PROSPEO_API_KEY` | Prospeo.io — LinkedIn contact search+enrich (100 credits/month) | blank |
| `ZEROBOUNCE_API_KEY` | ZeroBounce — email verification (100/month) | blank |
| `SNOV_CLIENT_ID` | Snov.io client ID (domain email search — requires paid plan) | blank |
| `SNOV_CLIENT_SECRET` | Snov.io client secret | blank |
| `HIGH_SCORE_THRESHOLD` | Minimum score for "high" tier leads | `70` |
| `MEDIUM_SCORE_THRESHOLD` | Minimum score for "medium" tier leads | `40` |
| `EMAIL_DAILY_LIMIT` | Max emails sent per day | `50` |
| `TB_CONTINGENCY_FEE` | Troy & Banks fee ratio for revenue estimates | `0.24` |
| `DEPLOY_ENV` | `local` disables API key auth on routes | `local` |

---

## 8. Dashboard Pages

| Page | Route | What it shows |
|---|---|---|
| **Chat Agent** | `/chat` | Conversational interface — primary way to use the platform |
| **Scout Live** | `/scout` | Trigger a company search and watch cards appear in real time |
| **Leads** | `/leads` | All companies with filters (tier, industry, status, score) — approve/reject leads |
| **Email Review** | `/emails` | Pending email drafts — approve / edit+approve / reject / regenerate |
| **Triggers** | `/triggers` | Manual pipeline controls: Scout, Analyst, Enrich, Writer, Verify, Backfill phones |
| **Pipeline** | `/pipeline` | Agent health, stage counts, recent activity feed |
| **Reports** | `/reports` | Weekly summary, top leads chart, pipeline value |

---

## 9. Observability & Monitoring

Three ways to see what the agent is doing, from quickest to most detailed.

### Option 1 — Docker Logs (always available)

```bash
docker logs lead-api -f
```

Shows HTTP requests, errors, and when tracing is enabled or disabled at startup.
Every chat message logs the run_id and tool calls at INFO level.

### Option 2 — LangSmith (recommended — visual trace per message)

LangSmith is LangChain's purpose-built tracing dashboard. It shows every LLM call,
which tool the agent chose, what arguments were passed, token counts, and latency —
all in a visual timeline.

**Setup (one time):**

1. Sign up free at **https://smith.langchain.com**
2. Go to Settings → API Keys → Create API Key
3. Add your key to `.env`:

```env
LANGCHAIN_TRACING_V2=true
LANGCHAIN_API_KEY=ls__your_key_here
LANGCHAIN_PROJECT=utility-lead-platform
```

4. Rebuild and restart the API:

```bash
docker build -f api/Dockerfile -t utility-lead-api . && docker restart lead-api
```

**What you see per chat message:**

```
smith.langchain.com → Projects → utility-lead-platform

  Trace: "find 10 healthcare companies in Buffalo NY"
  ├── [llm]   ChatOllama          1.2s   → chose search_companies tool
  ├── [tool]  search_companies    4.8s   → found=5, industry=healthcare
  └── [llm]   ChatOllama          0.9s   → wrote final reply
       Total: 6.9s | 312 tokens in | 48 tokens out
```

**Login:** https://smith.langchain.com → sign in with your account → Projects tab → `utility-lead-platform`

### Option 3 — Database Query (audit trail)

Every tool call and run is persisted in PostgreSQL. Query any time:

```sql
-- Last 10 agent runs with status
SELECT id, trigger_source, status, current_stage,
       companies_found, error_message, created_at
FROM agent_runs
ORDER BY created_at DESC LIMIT 10;

-- Every tool call in a specific run
SELECT agent, action, status, output_summary, duration_ms
FROM agent_run_logs
WHERE run_id = '<paste-run-id-from-chat>'
ORDER BY logged_at ASC;

-- All failed runs
SELECT id, error_message, created_at
FROM agent_runs
WHERE status = 'failed'
ORDER BY created_at DESC;
```

Or via the API (no DB client needed):
```
GET http://localhost:8001/pipeline/run/{run_id}
```

---

## 10. Database Tables

All tables live in the external PostgreSQL (AWS RDS). Migrations are in `database/migrations/`.

### Core Data Tables

| Table | Purpose | Key columns |
|---|---|---|
| `companies` | Every company Scout finds | `id`, `name`, `industry`, `city`, `website`, `source`, `status`, `run_id`, `quality_score` |
| `company_features` | Enrichment signals per company | `company_id`, `employee_count`, `location_count`, `utility_spend_estimate` |
| `lead_scores` | Analyst scoring output | `company_id`, `score`, `tier` (high/medium/low), `approved_human`, `approved_by` |
| `contacts` | Decision-maker contacts per company | `company_id`, `name`, `email`, `title`, `phone` |
| `email_drafts` | Writer-generated email drafts | `company_id`, `subject_line`, `body`, `approved`, `approved_by`, `sent_at` |
| `outreach_events` | Every email sent, opened, replied | `company_id`, `event_type`, `event_at`, `reply_sentiment`, `reply_content` |

### Run Tracking Tables

| Table | Purpose | Key columns |
|---|---|---|
| `agent_runs` | One row per pipeline run (chat or Airflow) | `id`, `trigger_source`, `status`, `current_stage`, `companies_found`, `drafts_created`, `started_at` |
| `agent_run_logs` | Step-by-step audit log per run | `run_id`, `agent`, `action`, `status`, `output_summary`, `duration_ms` |
| `human_approval_requests` | Human-in-loop queue | `run_id`, `approval_type` (leads/emails), `status` (pending/approved/rejected), `approved_by` |

### Learning Tables

| Table | Purpose | Who writes | Who reads |
|---|---|---|---|
| `source_performance` | Quality score per Scout source per industry/location | Scout (after each run) | Scout (next run — ranks sources best-first) |
| `email_win_rate` | Open/reply rate per email template per industry | Tracker (after reply events) | Writer (before drafting — picks best template) |

### Migration Files

```
database/migrations/
  001_create_companies.sql
  002_create_contacts.sql
  003_create_company_features.sql
  004_create_lead_scores.sql
  005_create_email_drafts.sql
  006_create_outreach_events.sql
  007_create_directory_sources.sql
  008_create_agent_runs.sql           ← run tracking
  009_create_agent_run_logs.sql       ← audit log
  010_create_source_performance.sql   ← Scout learning
  011_create_email_win_rate.sql       ← Writer learning
  012_create_human_approval_requests.sql  ← human-in-loop queue
  013_alter_companies_add_run_id.sql  ← links companies to runs
```

---

## 11. API Reference

Full Swagger docs at `http://localhost:8001/docs`. Key endpoints:

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/chat` | Send a message to the chat agent |
| `GET` | `/leads` | Fetch leads with optional filters |
| `PATCH` | `/leads/{id}/approve` | Approve a single lead |
| `PATCH` | `/leads/{id}/reject` | Reject a single lead |
| `POST` | `/approvals/leads` | Bulk approve/reject leads for a run (Phase 2) |
| `GET` | `/approvals/leads` | List pending lead approval requests (Phase 2) |
| `GET` | `/emails/pending` | Fetch unapproved email drafts |
| `PATCH` | `/emails/{id}/approve` | Approve an email draft |
| `PATCH` | `/emails/{id}/edit` | Edit subject/body of a draft |
| `POST` | `/trigger/scout` | Trigger Scout only (background) |
| `POST` | `/trigger/analyst` | Trigger Analyst scoring for all unscored companies |
| `POST` | `/trigger/full` | Trigger full pipeline (background) |
| `GET` | `/trigger/{id}/status` | Poll status of a triggered run |
| `GET` | `/pipeline/status` | Current stage counts + pipeline value |
| `GET` | `/pipeline/health` | Health check for all services |
| `GET` | `/pipeline/run/{run_id}` | Status and logs for one agent run |
| `GET` | `/reports/weekly` | Weekly performance summary |
| `GET` | `/health` | API health check |

---

## 12. Troubleshooting

### Chat returns "could not reach the API server"
API container is not running or crashed.
```bash
docker logs lead-api --tail 30
docker restart lead-api
```

### Chat agent fails with import error
Rebuild the API image — a dependency may be missing.
```bash
docker build -f api/Dockerfile -t utility-lead-api . && docker restart lead-api
```

### Ollama not responding (chat fails silently)
```bash
ollama serve          # start Ollama if not running
ollama list           # confirm llama3.2 is pulled
curl http://localhost:11434/api/tags
```
Inside Docker, Ollama is reached via `host.docker.internal:11434` — confirm
`OLLAMA_BASE_URL=http://host.docker.internal:11434` in `.env`.

### Scout finds 0 companies
- Check `TAVILY_API_KEY` is set and quota not exceeded
- Confirm `SCRAPERAPI_KEY` is valid
- Check API logs: `docker logs lead-api -f`

### Database connection error
- Confirm `DATABASE_URL` in `.env` points to your PostgreSQL instance
- Check the DB is accessible from Docker: run `docker exec lead-api python -c "from database.connection import engine; print(engine.url)"`

### Frontend blank page / 404 on refresh
The nginx container handles SPA routing. If it shows a raw nginx error, rebuild:
```bash
docker build -f dashboard/Dockerfile -t utility-lead-frontend . && docker restart lead-frontend
```

### SendGrid emails not delivering
- Verify sender email is authenticated in SendGrid dashboard
- Confirm `SENDGRID_FROM_EMAIL` matches the verified sender identity
- Check SendGrid activity feed for blocked/rejected messages
