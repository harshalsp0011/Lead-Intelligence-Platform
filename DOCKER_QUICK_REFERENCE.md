# Docker Quick Reference - Utility Lead Platform

## Current Setup

- Database is external AWS RDS via DATABASE_URL in .env.
- No local postgres service is used.
- Agents run in one unified service: agents.

## Start / Stop

Start all (foreground):
```bash
cd utility-lead-platform
docker-compose up --build
```

Start all (background):
```bash
docker-compose up --build -d
```

Stop all:
```bash
docker-compose down
```

Clean restart:
```bash
docker-compose down --remove-orphans
docker-compose up -d
```

## Status / Logs

Status:
```bash
docker-compose ps
docker-compose ps -a
```

Logs:
```bash
docker-compose logs -f
docker-compose logs -f api
docker-compose logs -f agents
docker-compose logs -f airflow
docker-compose logs -f frontend
docker-compose logs -f grafana
docker-compose logs -f prometheus
```

## Services and Dockerfiles

| Service | Source | Port | Dockerfile |
|---|---|---|---|
| api | custom image | 8001 | api/Dockerfile |
| frontend | custom image | 3000 | dashboard/Dockerfile |
| agents | custom image | 8000 | agents/Dockerfile |
| airflow | apache/airflow:2.8.0 | 8080 | none |
| grafana | grafana/grafana:latest | 3001 | none |
| prometheus | prom/prometheus | 9090 | none |

## URLs

- Frontend: http://localhost:3000
- API docs: http://localhost:8001/docs
- Airflow: http://localhost:8080
- Grafana: http://localhost:3001
- Prometheus: http://localhost:9090

## Important Checks

Confirm RDS URL:
```bash
grep '^DATABASE_URL=' .env
```

Confirm API can reach DB:
```bash
docker-compose exec api python -c "from sqlalchemy import text; from database.connection import SessionLocal; db=SessionLocal(); db.execute(text('SELECT 1')); db.close(); print('DB OK')"
```

Confirm Airflow scheduler starts:
```bash
docker-compose logs airflow --tail=80
```
Look for: Starting the scheduler

## Key Files

- docker-compose.yml
- .env
- requirements.txt
- api/
- agents/
- dashboard/src/
- dags/
- monitoring/prometheus/prometheus.yml
- monitoring/grafana/dashboard.json

## Notes

- Old commands for postgres/scout containers are not applicable in this setup.
- agents may exit with code 0 depending on workload/entrypoint behavior.

Last updated: March 16, 2026
