# Chatbot Architecture — How It Works

## Overview

The chatbot is the **primary interface** for the platform. The user types natural language
and the agent decides what to do — no forms, no buttons required.

---

## Request Flow

```
User types message
       │
       ▼
React Chat UI (localhost:3000)
  src/pages/Chat.jsx
       │  POST /chat  { "message": "find 10 healthcare companies in Buffalo NY" }
       ▼
FastAPI  (localhost:8001)
  api/routes/chat.py
       │  calls run_chat(message, db)
       ▼
agents/chat_agent.py  ← LangChain ReAct agent
       │
       ├── Creates agent_runs row  (trigger_source="chat")
       │
       ├── Builds LLM:
       │     LLM_PROVIDER=ollama  →  ChatOllama (llama3.2 via host.docker.internal:11434)
       │     LLM_PROVIDER=openai  →  ChatOpenAI (GPT-4o-mini)
       │
       ├── Agent picks tool from:
       │     search_companies(industry, location, count)
       │     get_leads(tier, industry)
       │     get_outreach_history()
       │     get_replies()
       │     run_full_pipeline(industry, location, count)
       │
       ├── Tool executes → writes to DB → logs to agent_run_logs
       │
       └── Returns { reply: str, data: dict, run_id: str }
                        │
                        ▼
              Chat UI renders:
                - Text reply as message bubble
                - CompanyCard / LeadCard / ReplyCard  (inline data)
                - Run ID shown below agent message
```

---

## Tools the Agent Can Call

| Tool | Triggered when user says | What it does |
|---|---|---|
| `search_companies` | "find companies", "search for", "discover" | Runs Scout agent → saves companies to DB |
| `get_leads` | "show me leads", "high-tier leads", "scored leads" | Queries `companies + lead_scores` tables |
| `get_outreach_history` | "who did we email", "already contacted", "sent emails" | Queries `outreach_events` where type=sent |
| `get_replies` | "any replies?", "who replied", "interested prospects" | Queries `outreach_events` where type=replied |
| `run_full_pipeline` | "run the full pipeline", "start everything", "do a complete run" | Calls `orchestrator.run_full_pipeline()` → Scout + Analyst + Writer |

---

## What the Agent Tracks (Database)

Every chat message creates one `agent_runs` row:

```
agent_runs
├── id              (UUID)
├── trigger_source  = "chat"
├── trigger_input   = { "message": "..." }
├── status          started → scout_running → scout_complete → completed / failed
├── current_stage   chat → scout → analyst → writer → outreach
├── companies_found (filled by search_companies tool)
├── companies_scored
├── drafts_created
└── error_message   (if failed)
```

Every tool call appends one row to `agent_run_logs`:
```
agent_run_logs
├── run_id          (FK to agent_runs)
├── agent           "scout" | "chat" | "orchestrator"
├── action          "companies_found" | "get_leads" | etc.
├── status          "success" | "failure"
├── output_summary  human-readable result
└── duration_ms
```

---

## UI Rendering

The chat UI (`src/pages/Chat.jsx`) renders agent responses in two parts:

1. **Text bubble** — the agent's natural language reply
2. **Inline data cards** — structured results from the tool call:
   - `CompanyCard` — name, industry, city, website, source badge
   - `LeadCard` — name, tier badge, score, approved status
   - `ReplyCard` — name, sentiment badge, reply snippet, date
   - `Pipeline Summary` — companies found, scored high/medium, drafts created

Quick suggestion buttons shown on first load:
- "Find 10 healthcare companies in Buffalo NY"
- "Show me all high-tier leads"
- "Which companies have we already emailed?"
- "Did anyone reply to our emails?"
- "Run the full pipeline for healthcare in Buffalo NY"

---

## LLM Configuration

```env
LLM_PROVIDER=ollama          # switch to "openai" for GPT-4o-mini
LLM_MODEL=llama3.2           # or "gpt-4o-mini"
OLLAMA_BASE_URL=http://host.docker.internal:11434   # Ollama on host machine
OPENAI_API_KEY=              # fill in if using openai
```

Switch providers by changing `LLM_PROVIDER` in `.env` and restarting the API container:
```bash
docker restart lead-api
```

---

## What Is Not Yet Connected (Future Phases)

| Tool | Status | Phase |
|---|---|---|
| `approve_leads(company_ids)` | Not yet added | Phase 2 |
| `approve_emails(draft_ids)` | Not yet added | Phase 3 |
| `draft_email(company_id)` | Not yet added | Phase 3 |
| Human-in-loop pause after Analyst | Not yet built | Phase 2 |
| Human-in-loop pause after Writer | Not yet built | Phase 3 |
| Auto email notification on reply | Not yet built | Phase 4 |

---

## Docker Container Management

```bash
# Start both containers
docker start lead-api lead-frontend

# Stop both
docker stop lead-api lead-frontend

# View API logs (see tool calls, errors)
docker logs lead-api -f

# Rebuild after code changes
docker build -f api/Dockerfile -t utility-lead-api . && docker restart lead-api
docker build -f dashboard/Dockerfile -t utility-lead-frontend . && docker restart lead-frontend
```
