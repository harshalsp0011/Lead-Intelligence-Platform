# Docker Deployment Guide - Utility Lead Platform

This is the single master doc for all setup steps and commands completed so far.

Current architecture:
- External AWS RDS is used for the database.
- No local postgres service is used in Compose.
- Compose services: api, frontend, airflow, grafana, prometheus, scout, analyst, writer, outreach, tracker, orchestrator.

## 1. Final Service and Database Setup

### Running services in docker-compose.yml
- api
- frontend
- airflow
- grafana
- prometheus
- scout
- analyst
- writer
- outreach
- tracker
- orchestrator

### Database
- External RDS from `.env`:
  - `DATABASE_URL=postgresql://...`
- Verified from `api` container with `SELECT 1`.

## 2. Files Used and Updated

### Core container/orchestration files
- `docker-compose.yml`
- `.env`
- `api/Dockerfile`
- `dashboard/Dockerfile`
- `agents/scout/Dockerfile`
- `agents/analyst/Dockerfile`
- `agents/writer/Dockerfile`
- `agents/outreach/Dockerfile`
- `agents/tracker/Dockerfile`
- `agents/orchestrator/Dockerfile`
- `requirements.txt`

### Agent folder READMEs updated for containerization
- `agents/scout/README.md`
- `agents/analyst/README.md`
- `agents/writer/README.md`
- `agents/outreach/README.md`
- `agents/tracker/README.md`
- `agents/orchestrator/README.md`

### Migration files executed
- `database/migrations/001_create_companies.sql`
- `database/migrations/002_create_company_features.sql`
- `database/migrations/003_create_lead_scores.sql`
- `database/migrations/004_create_contacts.sql`
- `database/migrations/005_create_email_drafts.sql`
- `database/migrations/006_create_outreach_events.sql`

## 3. Completed Steps Log (with commands)

### Step A - Environment setup and config fixes
Commands used:
```bash
cp .env.example .env
```

Key finalized values in `.env`:
```env
OLLAMA_BASE_URL=http://host.docker.internal:11434
DATABASE_URL=postgresql://<rds-user>:<rds-pass>@<rds-host>:5432/<rds-db>
```

Notes:
- `postgres://` was corrected to `postgresql://`.
- RDS URL is used instead of local Docker DB.

### Step B - Docker image setup
What was done:
- Added per-agent Dockerfiles for separate services.
- Kept dedicated Dockerfiles for API and frontend.

Files:
- `agents/scout/Dockerfile`
- `agents/analyst/Dockerfile`
- `agents/writer/Dockerfile`
- `agents/outreach/Dockerfile`
- `agents/tracker/Dockerfile`
- `agents/orchestrator/Dockerfile`
- `api/Dockerfile`
- `dashboard/Dockerfile`

### Step C - Compose architecture update (RDS + separate agents)
What was changed:
- Removed local `postgres` service.
- Added separate services: `scout`, `analyst`, `writer`, `outreach`, `tracker`, `orchestrator`.
- Set Airflow command to initialize DB and run scheduler:
  - `bash -c "airflow db init && airflow scheduler"`
- Added keepalive commands for separate agents so they remain `Up` in `docker-compose ps`.

Key command used:
```bash
docker-compose down --remove-orphans
docker-compose up --build -d
```

### Step D - Startup verification
Commands used:
```bash
docker-compose ps
docker-compose ps -a
docker-compose logs api --tail=30
docker-compose logs airflow --tail=80
```

Observed successful signals:
- API: `Application startup complete`
- Airflow: `Starting the scheduler`
- Frontend/Grafana/Prometheus containers up
- Separate agent services present: scout, analyst, writer, outreach, tracker, orchestrator

### Step E - Database migration execution (your Step 3.4 equivalent)
Since there is no local postgres container, migrations were run from `api` container against RDS.

Command used:
```bash
docker-compose exec api sh -lc 'set -e; for f in /app/database/migrations/001_create_companies.sql /app/database/migrations/002_create_company_features.sql /app/database/migrations/003_create_lead_scores.sql /app/database/migrations/004_create_contacts.sql /app/database/migrations/005_create_email_drafts.sql /app/database/migrations/006_create_outreach_events.sql; do echo "Running $f"; psql "$DATABASE_URL" -f "$f"; done; echo "--- tables ---"; psql "$DATABASE_URL" -c "\dt"'
```

Result:
- All migrations executed.
- Existing objects reported as `already exists, skipping` (safe idempotent behavior).
- Verified tables:
  - `companies`
  - `company_features`
  - `lead_scores`
  - `contacts`
  - `email_drafts`
  - `outreach_events`

## 4. Commands to Use Going Forward

### Start / stop
```bash
docker-compose up --build
docker-compose up --build -d
docker-compose down
```

### Reset/recreate stack
```bash
docker-compose down --remove-orphans
docker-compose up -d
```

### Status
```bash
docker-compose ps
docker-compose ps -a
```

### Logs
```bash
docker-compose logs -f
docker-compose logs -f api
docker-compose logs -f airflow
docker-compose logs -f frontend
docker-compose logs -f grafana
docker-compose logs -f prometheus
docker-compose logs -f scout
docker-compose logs -f analyst
docker-compose logs -f writer
docker-compose logs -f outreach
docker-compose logs -f tracker
docker-compose logs -f orchestrator
```

### DB connectivity check
```bash
docker-compose exec api python -c "from sqlalchemy import text; from database.connection import SessionLocal; db=SessionLocal(); db.execute(text('SELECT 1')); db.close(); print('DB OK')"
```

## 5. Important Notes

- Old commands using `docker-compose exec postgres ...` are not applicable in this setup.
- Local postgres URL `localhost:5432` is not used for application data in this setup.
- Separate agent containers are configured to stay `Up` for easier operational visibility.

## 6. PART 4 - Access Every Service (All URLs and What They Do)

| Service | URL | Purpose / Notes |
|---|---|---|
| React Dashboard | http://localhost:3000 | Frontend UI |
| FastAPI Backend | http://localhost:8001 | API base endpoint |
| FastAPI Docs (Swagger) | http://localhost:8001/docs | Interactive API docs |
| FastAPI Docs (Redoc) | http://localhost:8001/redoc | Alternate API docs |
| Airflow Scheduler | http://localhost:8080 | Airflow scheduler/web UI container. Login: `admin` / `admin` |
| Grafana Monitoring | http://localhost:3001 | Monitoring dashboards |
| Prometheus Metrics | http://localhost:9090 | Metrics collector UI |
| PostgreSQL DB | localhost:5432 | Not used in current setup (RDS is used instead) |
| Ollama LLM | http://localhost:11434 | Host machine Ollama endpoint used by containers via host.docker.internal |
| Tracker Webhook | http://localhost:8002 | Not exposed as a standalone service in current compose setup |

## 7. Quick Reality Check for This Setup

- Database is AWS RDS via `DATABASE_URL`, not local Postgres.
- Agent containers run as separate services: scout, analyst, writer, outreach, tracker, orchestrator.
- Tracker webhook remains not exposed on `:8002` unless you add a dedicated port mapping/service.
- Airflow mounts the project DAGs and Python code into the running container.

## 7.1 Airflow Login And DAG Loading

- Airflow URL: `http://localhost:8080`
- Username: `admin`
- Password: `admin`
- Airflow mounts `dags/`, `agents/`, `config/`, `database/`, and `data/` from the workspace.
- Restart Airflow after container-level config changes:

```bash
docker-compose restart airflow
```

## 8. Local Dashboard Usage

- URL: http://localhost:3000
- Login: no login needed in local mode

Pages:
- `/` or `/pipeline` -> Pipeline Overview (home)
- `/leads` -> All leads table with filters
- `/leads/{id}` -> Single lead detail
- `/emails/review` -> Email approval queue
- `/triggers` -> Manual run controls
- `/reports` -> Weekly metrics

First thing to do:
1. Go to `/triggers`.
2. Select Industry: Healthcare.
3. Set Location: Buffalo, NY.
4. Set Count: 10.
5. Click `Run Full Pipeline`.
6. Watch results appear in `/leads` after about 10-15 minutes.

Last updated: March 16, 2026
