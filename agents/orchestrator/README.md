# Orchestrator Agent Files

This folder contains cross-agent orchestration and pipeline monitoring utilities.

## Files

pipeline_monitor.py
Monitors pipeline health by reporting status counts, value rollups, infrastructure health,
stuck-condition warnings, and recent outreach activity.

Main functions:
- get_pipeline_counts(db_session)
- get_pipeline_value(db_session)
- check_agent_health()
- detect_stuck_pipeline(db_session)
- get_recent_activity(db_session, limit=10)

report_generator.py
Generates weekly/daily reporting payloads by aggregating company discovery,
scoring tiers, outreach activity, replies, pipeline value, and top active leads.

Main functions:
- generate_weekly_report(start_date, end_date, db_session)
- count_companies_found(start_date, end_date, db_session)
- count_leads_by_tier(start_date, end_date, db_session)
- count_emails_sent(start_date, end_date, db_session)
- count_replies_received(start_date, end_date, db_session)
- calculate_pipeline_value(db_session)
- get_top_leads(limit, db_session)

## Database Dependencies

The monitor reads from:
- companies
- company_features
- lead_scores
- email_drafts
- outreach_events
- contacts

## Service Checks

check_agent_health() probes:
- postgres
- ollama (http://localhost:11434)
- api (http://localhost:8001/health)
- airflow (http://localhost:8080/health)
- sendgrid key configured
- tavily key configured
- sendgrid from email configured

orchestrator.py
Main Orchestrator Agent entry point that controls the complete lead-generation
pipeline: scout → analyst → contact enrichment → writer → outreach.

Main functions:
- run_full_pipeline(industry, location, count, db_session)
- run_scout(industry, location, count, db_session)
- run_analyst(company_ids, db_session)
- run_contact_enrichment(company_ids, db_session)
- run_writer(db_session)
- run_outreach(db_session)
- generate_run_summary(scout_result, analyst_result, enrichment_result, writer_result)
- handle_agent_failure(agent_name, error, task_params, db_session)

task_manager.py
Routes tasks to individual agents, tracks their state (running / completed /
failed) in an in-process registry, supports retry logic up to 3 attempts, and
persists structured log lines to logs/task_log.txt.

Main functions:
- assign_task(agent_name, task_params, db_session)
- check_task_status(task_id)
- retry_failed_task(task_id, db_session)
- log_task_result(agent_name, params, result, duration_seconds)

Agent dispatch table:
- 'scout'    → scout_agent.run(industry, location, count, db_session)
- 'analyst'  → analyst_agent.run(company_ids, db_session)
- 'writer'   → writer_agent.run(company_ids, db_session, run_id)  ← run_id for AgentRun tracking
- 'outreach' → outreach_agent.process_followup_queue(db_session)
- 'tracker'  → tracker_agent.run_daily_checks(db_session)

## Usage

1. Call get_pipeline_counts(...) to populate dashboard stage totals.
2. Call get_pipeline_value(...) to compute active high-tier pipeline value.
3. Call detect_stuck_pipeline(...) for issue banners/alerts.
4. Call get_recent_activity(...) for latest outreach timeline rows.
5. Call check_agent_health() in diagnostics views or scheduled heartbeat jobs.
6. Call generate_weekly_report(...) for weekly/daily summary export payloads.
7. Call get_top_leads(...) for ranking cards in operations dashboards.
8. Call assign_task(agent_name, params, db_session) to dispatch work to any agent.
9. Call check_task_status(task_id) to poll the current task state.
10. Call retry_failed_task(task_id, db_session) to retry a failed task (max 3 times).

## Container

All agents (including orchestrator) run inside the `api` container — there is no separate
orchestrator container. The `api` service imports and calls agent modules directly.

```
docker-compose up
  ├── api       (port 8001)  FastAPI + all agents in one process
  └── frontend  (port 3000)  nginx + React
```
