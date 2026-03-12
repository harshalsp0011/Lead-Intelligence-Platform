# API Layer

This folder contains the FastAPI application layer: shared dependencies,
request/response models, and route handlers.

## Files

dependencies.py
Shared FastAPI dependencies injected into route handlers via `Depends(...)`.

Functions:
- `get_db()` — yields a SQLAlchemy session per request; closes it in finally block
- `get_settings_dep()` — returns the cached Settings singleton
- `verify_api_key(request, settings)` — validates `X-API-Key` header; raises HTTP 401
  on mismatch; skips check when `DEPLOY_ENV=local`

## Folders

### models/

Pydantic v2 request and response schemas used by route handlers.

**lead.py**
- `LeadResponse` — full lead record
- `LeadApproveRequest` — approve a lead (approved_by)
- `LeadRejectRequest` — reject a lead (rejected_by, rejection_reason)
- `LeadListResponse` — paginated leads with tier counts
- `LeadFilterParams` — optional filters + pagination (industry, state, tier, score range, dates)

**email.py**
- `EmailDraftResponse` — full draft record
- `EmailApproveRequest` — approve a draft (approved_by)
- `EmailEditRequest` — human edit (edited_by, new_subject_line, new_body)
- `EmailRejectRequest` — reject a draft
- `EmailListResponse` — drafts with status-level counts

**pipeline.py**
- `PipelineStatusResponse` — stage counts + pipeline value
- `AgentHealthResponse` — per-service health dicts; `overall_status` computed field
  (healthy / warning / degraded)
- `ActivityItem` — single outreach event
- `RecentActivityResponse` — activity feed list

**trigger.py**
- `TriggerRequest` — start a pipeline run (industry, location, count, run_mode);
  validates allowed industries and run modes
- `TriggerResponse` — immediate acknowledgement with trigger_id and status
- `TriggerStatusResponse` — polling status (completed_at, duration, result_summary)

**report.py**
- `WeeklyReportResponse` — full weekly aggregation (sourcing, scoring, outreach,
  replies, outcomes, pipeline value)
- `TopLeadItem` — single ranked lead entry
- `TopLeadsResponse` — ranked lead list

### routes/

FastAPI router modules, one file per resource.

**leads.py** — prefix `/leads`
- `GET  /leads`                       — paginated list with optional filters (industry, state, tier, score range, dates)
- `GET  /leads/high`                  — high-tier only, ordered by score DESC
- `GET  /leads/{company_id}`          — single lead details
- `PATCH /leads/{company_id}/approve` — set approved_human=true, company status='approved'
- `PATCH /leads/{company_id}/reject`  — archive company, log rejection reason

**emails.py** — prefix `/emails`
- `GET  /emails`                        — paginated draft list (approved_only filter)
- `GET  /emails/pending`                — unapproved drafts, oldest first
- `GET  /emails/{draft_id}`             — single draft details
- `PATCH /emails/{draft_id}/approve`    — mark approved_human=true
- `PATCH /emails/{draft_id}/edit`       — update subject_line and/or body
- `PATCH /emails/{draft_id}/reject`     — hard-delete draft, log reason
- `POST  /emails/{draft_id}/regenerate` — delete + re-generate via writer agent

Email and lead routes now read and write through `database/orm_models.py`
instead of raw SQL text statements. Failed API-key checks and not-found API
paths are logged before raising to keep request failures observable.

**pipeline.py** — prefix `/pipeline`
- `GET /pipeline/status`   — stage counts + pipeline value + total_active
- `GET /pipeline/health`   — per-service health + computed overall_status
- `GET /pipeline/activity` — recent outreach activity feed (limit param)
- `GET /pipeline/issues`   — stuck-pipeline issue strings

**triggers.py** — prefix `/trigger`
- `POST /trigger/full`              — run full pipeline in background (returns trigger_id)
- `POST /trigger/scout`             — scout only
- `POST /trigger/analyst`           — analyst only (queries unscored companies automatically)
- `POST /trigger/writer`            — writer only
- `POST /trigger/outreach`          — outreach only
- `GET  /trigger/{trigger_id}/status` — poll status: running / completed / failed

**reports.py** — prefix `/reports`
- `GET /reports/weekly`    — full weekly summary (start_date / end_date query params)
- `GET /reports/top-leads` — top high-tier leads ranked by score (limit param)
- `GET /reports/funnel`    — funnel drop-off percentages across all pipeline stages

## main.py

FastAPI app entry point:
- Title: "Utility Lead Intelligence Platform API", version 1.0.0
- CORS allowed origin: `http://localhost:3000`
- `GET /health` — unauthenticated liveness check
- Startup event: probes DB connection and logs result
- Run: `python api/main.py` or `uvicorn api.main:app --host 0.0.0.0 --port 8001`

## Authentication

All protected routes should declare `verify_api_key` as a dependency:

```python
from fastapi import Depends
from api.dependencies import verify_api_key

@router.get("/leads", dependencies=[Depends(verify_api_key)])
def list_leads(...):
    ...
```

Set `API_KEY=<secret>` in `.env` for production.
Set `DEPLOY_ENV=local` to bypass authentication during local development.

## Usage

```python
from fastapi import Depends
from sqlalchemy.orm import Session
from api.dependencies import get_db, get_settings_dep, verify_api_key

@router.get("/example", dependencies=[Depends(verify_api_key)])
def example_route(db: Session = Depends(get_db)):
    ...
```
