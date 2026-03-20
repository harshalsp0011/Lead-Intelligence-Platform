# Phase 3 — Chat Resilience, Live Progress & UI Fixes

## What We Built

This document covers the work done to make the chat and pipeline UI reliable across page refreshes, mid-run navigation, and agent failures.

---

## 1. Background-Task Chat (Non-Blocking)

### Problem
`POST /chat` ran synchronously — the browser had to wait the full Scout runtime (60–120 s) for a response. After 30 seconds the browser timeout fired and the user saw "Could not reach the API server."

### Solution
**`api/routes/chat.py`** was changed to a background-thread pattern:

```
POST /chat  →  returns {run_id, status: "started"} immediately
                background thread runs run_chat(message, db, run_id)
                stores result in _results dict keyed by run_id

GET /chat/result/{run_id}  →  {status: "pending"|"done"|"error", reply, data}
```

The frontend polls `/chat/result/{run_id}` every 2 seconds until `status !== "pending"`.

**Files changed:**
- `api/routes/chat.py` — full rewrite to background-thread + in-memory result store
- `agents/chat_agent.py` — `run_chat()` now accepts optional `run_id` parameter so the route can pre-generate it before spawning the thread
- `dashboard/src/services/api.js` — added `startChat(message)` and `fetchChatResult(runId)`

---

## 2. Live Progress Steps in Chat

### Problem
While Scout was running the user saw generic "Agent is working…" dots with no feedback about what was happening.

### Solution
`agents/scout/scout_agent.py` writes human-readable progress messages to `agent_run_logs` at every phase:

| Phase | Progress message written |
|---|---|
| Start | `"Starting Scout — looking for 10 healthcare companies in Buffalo NY"` |
| Phase 1 | `"Checking N configured directory source(s)..."` |
| Per directory | `"Scraping directory: <name>..."` / `"Directory <name> failed — skipping"` |
| Phase 2 | `"Searching Tavily for <industry> directories in <location>..."` |
| Phase 3 Google | `"Trying Google Maps for <industry> in <location>..."` |
| Phase 3 Yelp | `"Trying Yelp for <industry> in <location>..."` |
| Per result | `"Found N companies from Google Maps (total: N)"` |
| Done | `"Scout complete — saved N of N requested companies"` |

The frontend polls `/pipeline/run/{run_id}` in parallel with `/chat/result/{run_id}`. Progress steps from `recent_logs` are shown in the typing indicator bubble, with `✓` for completed steps and `→` for the current step.

**Files changed:**
- `agents/scout/scout_agent.py` — added `_log_progress()` helper + calls at each phase
- `agents/chat_agent.py` — logs "Scout starting…" before calling scout
- `api/routes/pipeline.py` — `GET /pipeline/run/{run_id}` now returns ALL logs (was capped at last 5)
- `dashboard/src/pages/Chat.jsx` — `ProgressIndicator` component replaces generic `TypingIndicator`

---

## 3. Chat History Persistence (localStorage)

### Problem
Chat messages were in React `useState` — cleared on every page refresh.

### Solution
Messages are persisted to `localStorage` under the key `chat_messages`.

```js
// Restore on mount
const [messages, setMessages] = useState(() => {
  try {
    const saved = localStorage.getItem('chat_messages');
    return saved ? JSON.parse(saved) : [WELCOME_MESSAGE];
  } catch {
    return [WELCOME_MESSAGE];
  }
});

// Persist on every change
useEffect(() => {
  localStorage.setItem('chat_messages', JSON.stringify(messages));
}, [messages]);
```

**What is stored:** Both user messages AND agent replies, including the full `data` payload (company cards, lead cards, pipeline summaries). All fields are plain JSON-serializable objects so they restore correctly.

**Clear history button** added to the Chat header — calls `localStorage.removeItem('chat_messages')` and resets to welcome message.

**Files changed:**
- `dashboard/src/pages/Chat.jsx`

---

## 4. Mid-Run Navigation Fix (sessionStorage)

### Problem
If the user navigated away from the Chat page while a Scout run was in progress:
- The React component unmounted, destroying the polling `setTimeout`
- The backend continued running and stored the result in `_results`
- When the user came back, only their original question was visible
- The agent reply never arrived because polling was dead

### Solution
The active `run_id` is persisted to `sessionStorage` under `chat_active_run_id`.

**Flow:**

```
User sends message
  → startChat() returns run_id
  → sessionStorage.setItem('chat_active_run_id', run_id)   ← saved
  → polling starts

User navigates to Pipeline page
  → Chat component unmounts
  → polling timer is cleared  (component cleanup)
  → BUT run_id still in sessionStorage                      ← survives

Backend finishes the Scout run
  → result stored in _results[run_id] = {status: "done", ...}

User navigates back to Chat
  → Chat component mounts
  → loading = true  (because sessionStorage has run_id)
  → useEffect on mount: reads run_id, resumes polling immediately
  → fetchChatResult(run_id) → {status: "done", ...}
  → agent reply bubble appears with full data cards          ← fixed
  → sessionStorage.removeItem('chat_active_run_id')
```

**sessionStorage vs localStorage:**
- `sessionStorage` is used for the active run_id (not `localStorage`) because it lives for the browser tab session only — if the user opens a new tab or closes the browser, the stale run_id is gone automatically.
- `localStorage` is used for message history because that should persist across sessions.

**Files changed:**
- `dashboard/src/pages/Chat.jsx`

---

## 5. Edge Cases Handled

### Server Restart Mid-Run
If Docker is restarted while a run is in progress, the `_results` in-memory dict is wiped. On next poll, `GET /chat/result/{run_id}` returns 404.

The frontend detects the 404 and shows a clear message instead of polling forever:
```
"The agent was still running when the server restarted. Please try your request again."
```

Then clears `sessionStorage` and stops polling.

### localStorage Full
If localStorage reaches the browser limit (~5 MB), the save silently skips via try/catch — the chat continues working, messages just won't persist that session.

### Polling Survives Network Hiccups
If both `fetchRunStatus` and `fetchChatResult` throw network errors, the poll retries in 3 seconds (instead of 2) — giving the network time to recover before hammering again.

### Run Already Done When User Returns
If the user navigated away and the run completed while they were gone, the first poll on remount immediately gets `{status: "done"}` — no waiting, the agent reply appears within 1 second of returning to the Chat page.

---

## 6. Leads Page Fix — Datetime Crash

### Problem
`GET /leads` returned HTTP 500 crashing with:
```
TypeError: can't compare offset-naive and offset-aware datetimes
```
Companies saved from Google Maps/Yelp stored `updated_at` as timezone-naive datetime, but the sort fallback was timezone-aware. Python cannot compare the two.

### Fix
Added `_aware()` helper in `_query_leads()` that normalizes any naive datetime to UTC-aware before sorting:

```python
def _aware(dt):
    if not dt:
        return datetime.min.replace(tzinfo=timezone.utc)
    if isinstance(dt, datetime) and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt

rows.sort(key=lambda item: _aware(item.get("updated_at")), reverse=True)
```

**Files changed:**
- `api/routes/leads.py`

---

## 7. Leads Page — Retry Button

Error banner now includes a **Retry** button so transient failures (RDS cold start, network blip) can be recovered without a full page refresh.

**Files changed:**
- `dashboard/src/pages/Leads.jsx`

---

## 8. Triggers Page — Real Result Summary

### Problem
After a trigger run completed, the page showed "✅ Completed" with no information about what was actually saved.

### Solution
`ActiveRunStatus` now reads `result_summary` from `GET /trigger/{id}/status` and renders a results card:

```
Run Results
  Companies saved:  10
  High tier:         3
  Medium tier:       5
  Contacts found:    2
  Email drafts:      1
  [ View in Leads page → ]
```

The "View in Leads page" button uses `useNavigate` to jump to `/leads` directly.

**Files changed:**
- `dashboard/src/pages/Triggers.jsx`

---

## 9. Scout Domain Blocklist

### Problem
Tavily returned URLs for sites that can never be scraped (login-required, paywalled, anti-bot). The scout was spending 60–90 seconds attempting and failing all of them before reaching Google Maps/Yelp.

### Solution
Added `_UNSCRAPPABLE_DOMAINS` blocklist in `search_client.py`. Tavily results matching any blocked domain are silently skipped before any HTTP request is made:

```python
_UNSCRAPPABLE_DOMAINS = {
    "glassdoor.com", "linkedin.com", "zoominfo.com", "seamless.ai",
    "bizjournals.com", "reddit.com", "facebook.com", "instagram.com",
    "indeed.com", "yelp.com",  # Yelp used via API in Phase 3, not scraped
    ... # 27 domains total
}
```

**Effect:** Scout now reaches Google Maps/Yelp (the real data sources) 60–90 seconds faster.

**Files changed:**
- `agents/scout/search_client.py`

---

## Architecture Note — What This Is NOT

**This is not RAG (Retrieval Augmented Generation).**

RAG = embed your own documents → store in vector DB → at query time, search for similar chunks → inject into LLM prompt.

**This is an agentic pipeline:**
- LangChain `create_agent` with tool-calling
- LLM (llama3.2 via Ollama, running locally on the host Mac) reads the system prompt + user message
- Decides which tool to call: `search_companies`, `get_leads`, `get_replies`, etc.
- Tools make live API calls to Google Maps, Yelp, Tavily, PostgreSQL
- LLM reads tool result, writes the reply

**"Local" in `.env`:**
- `DEPLOY_ENV=local` → API key auth is bypassed (no `X-API-Key` header needed)
- `LLM_PROVIDER=ollama` + `OLLAMA_BASE_URL=http://192.168.65.254:11434` → LLM runs on your Mac via Ollama, not OpenAI cloud — zero per-token cost

---

## Deployment State

Both services running via Docker Compose:

| Service | Container | Port |
|---|---|---|
| FastAPI backend | `utility-lead-platform-api-1` | 8001 |
| React frontend (nginx) | `utility-lead-platform-frontend-1` | 3000 |

Rebuild after any code change:
```bash
# Both services
docker compose up --build -d && docker image prune -f

# API only
docker compose up --build api -d

# Frontend only
docker compose up --build frontend -d
```
