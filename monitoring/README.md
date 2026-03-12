# Monitoring Setup

Prometheus and Grafana configuration for monitoring the Utility Lead Platform.

## Directory Structure

```
monitoring/
├── prometheus/
│   └── prometheus.yml       # Prometheus scrape configuration
├── grafana/                 # Grafana dashboard configs (future)
└── README.md               # This file
```

## Prometheus Configuration

### Files

- **prometheus.yml**: Main Prometheus configuration with 3 scrape jobs

### Scrape Jobs

1. **utility-lead-api** (localhost:8001)
   - Interval: 15 seconds
   - Metrics endpoint: `/metrics`
   - Collects: Pipeline metrics, email stats, agent performance

2. **postgres-exporter** (localhost:9187)
   - Interval: 30 seconds
   - Collects: Database size, query performance, table stats

3. **airflow** (localhost:8080)
   - Interval: 30 seconds
   - Metrics endpoint: `/metrics`
   - Collects: DAG runs, task status, scheduler health

### Key Metrics Collected

#### From API

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `leads_found_total` | Counter | — | Total companies found by Scout agent |
| `leads_scored_total` | Counter | — | Total leads scored by Analyst agent |
| `leads_by_tier_total` | Counter | tier | Count of leads by tier (high/medium/low) |
| `emails_sent_total` | Counter | — | Total emails sent by Writer agent |
| `emails_opened_total` | Counter | — | Total emails opened by recipients |
| `emails_replied_total` | Counter | — | Total emails with replies |
| `pipeline_value_dollars` | Gauge | — | Current total pipeline value in USD |
| `agent_run_duration_seconds` | Histogram | — | Time taken for agent runs (buckets: 1s to 30min) |
| `agent_errors_total` | Counter | agent_name | Errors per agent (scout/analyst/writer/tracker/outreach/orchestrator) |

#### From PostgreSQL

| Metric | Type | Description |
|--------|------|-------------|
| `pg_up` | Gauge | Database is up (1) or down (0) |
| `pg_database_size_bytes` | Gauge | Total database size in bytes |
| `pg_stat_user_tables_seq_scan` | Gauge | Sequential scans per table |
| `pg_stat_user_tables_idx_scan` | Gauge | Index scans per table |

#### From Airflow

| Metric | Type | Description |
|--------|------|-------------|
| `airflow_dag_status` | Gauge | DAG state (success=1, failure=0, running=2) |
| `airflow_dag_duration_seconds` | Gauge | Duration of DAG runs |
| `airflow_task_duration_seconds` | Gauge | Duration of individual tasks |
| `airflow_scheduler_heartbeat` | Gauge | Scheduler health (up=1) |

## Setup Instructions

### Prerequisites

- Docker and Docker Compose (recommended)
- OR local Prometheus installation
- API running on localhost:8001
- PostgreSQL exporter running on localhost:9187
- Airflow running on localhost:8080

### Option 1: Docker Compose

Add to docker-compose.yml:

```yaml
prometheus:
  image: prom/prometheus:latest
  container_name: prometheus
  ports:
    - "9090:9090"
  volumes:
    - ./monitoring/prometheus/prometheus.yml:/etc/prometheus/prometheus.yml
    - prometheus_data:/prometheus
  command:
    - '--config.file=/etc/prometheus/prometheus.yml'
    - '--storage.tsdb.path=/prometheus'

volumes:
  prometheus_data:
```

Run:
```bash
docker-compose up prometheus
```

### Option 2: Local Installation

1. Download Prometheus from https://prometheus.io/download/
2. Extract and copy prometheus.yml:
   ```bash
   cp monitoring/prometheus/prometheus.yml /path/to/prometheus/prometheus.yml
   ```
3. Start Prometheus:
   ```bash
   ./prometheus --config.file=prometheus.yml
   ```

### Verify Setup

1. Access Prometheus UI: http://localhost:9090
2. Go to Status → Targets to verify all 3 jobs are healthy (green)
3. Try a query in the Graph tab, e.g., `leads_found_total`

## Grafana Integration (Future)

Grafana dashboards can be configured to connect to Prometheus on port 9090 and visualize:
- Real-time pipeline value
- Lead conversion funnel
- Email metrics (sent, open rate, reply rate)
- Agent performance (runs, errors, duration)
- Database health and query performance

## Troubleshooting

**Job showing DOWN (red)**
- Verify the target service is running on the specified port
- Check firewall permissions
- Confirm metrics endpoint is enabled in the service

**No metrics appearing**
- Ensure metrics endpoint is returning valid Prometheus format (text/plain)
- Check scrape logs in Prometheus UI (Status → Warnings)
- Verify job names don't conflict

**Query returns "no data"**
- Wait 1-2 minutes for first scrape to complete
- Check metric names match exactly (case-sensitive)
- Verify job is up in Status → Targets

## Next Steps

1. Implement metrics in API ([requirements](../api/README.md))
2. Configure postgres_exporter service
3. Expose Airflow metrics endpoint
4. Create Grafana dashboards
5. Define alerting rules in prometheus.yml
