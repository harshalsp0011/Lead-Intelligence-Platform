# DAGs

This folder contains Apache Airflow DAG definitions for scheduled pipeline work.

## Files

weekly_scout_dag.py
Runs every Monday at 9:00 AM, loads weekly scout targets, checks how many
companies have already been found this week, runs scout discovery for the
remaining target, validates the batch, sends a Slack completion message, and
hands the validated company IDs to the analyst stage.

Main task callables:
- load_target_config()
- check_existing_counts()
- run_scout_task()
- validate_scout_results()
- notify_scout_complete()
- trigger_analyst_dag()

daily_analyst_dag.py
Runs daily at 10:00 AM, discovers unscored companies, runs analyst scoring,
enriches high-tier leads with contacts, calculates pipeline value, and hands
off approved leads to the writer stage.

Main task callables:
- fetch_unscored_companies()
- run_analyst_task()
- filter_high_score_leads()
- run_contact_enrichment()
- notify_analyst_complete()
- trigger_writer_task()

daily_tracker_dag.py
Runs daily at 8:00 AM, sends scheduled followup emails, monitors daily email
limits, detects and resolves stale leads, marks completed sequences, and sends
a daily pipeline summary with active lead counts and metric rollups.

Main task callables:
- check_followup_queue()
- send_due_followups()
- check_daily_limit()
- scan_stale_leads()
- update_sequence_completions()
- send_daily_summary()

manual_trigger_dag.py
Manual on-demand DAG triggered via Airflow UI or API. Allows operators to run
specific pipeline stages (full, scout only, analyst only, or writer only) with
custom parameters. Logs trigger events and sends completion notifications.

Main task callables:
- validate_trigger_inputs()
- run_selected_mode()
- log_manual_trigger()
- notify_trigger_complete()

DAG parameters:
- `industry`: One of healthcare, hospitality, manufacturing, retail, public_sector, office
- `location`: City, ST format (e.g., "Buffalo, NY")
- `count`: Number to scout (5–100, default 20)
- `run_mode`: One of full, scout_only, analyst_only, writer_only

## Configuration

The weekly scout DAG reads its target settings from `config.settings` first and
falls back to environment variables when the settings object does not define
them yet.

Supported scout values:
- `TARGET_INDUSTRIES`: comma-separated industries or `all`
- `TARGET_LOCATIONS`: comma-separated `City, ST` values or `all`
- `SCOUT_WEEKLY_TARGET_COUNT`: weekly company target count

The daily analyst DAG uses existing database and settings configuration without
additional environment setup beyond typical Slack webhook requirements.

## Usage

1. Make sure Airflow can import the project root and the project dependencies.
2. For weekly scout: configure the weekly target environment variables if desired
   (otherwise uses built-in `all` filters).
3. Enable the DAGs in Airflow and verify Slack and database access.
4. The weekly scout DAG runs Mondays at 9:00 AM and triggers the daily analyst DAG.
5. The daily analyst DAG runs automatically each day at 10:00 AM independent of the scout DAG.