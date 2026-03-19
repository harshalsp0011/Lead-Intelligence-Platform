-- Creates agent_runs table.
-- Tracks every pipeline run triggered from chat or Airflow.
-- One row per run. Holds target context, current stage, status, counts, and errors.
-- Dependencies: pgcrypto extension (already created in 001_create_companies.sql).

CREATE TABLE IF NOT EXISTS agent_runs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- how the run was started
    trigger_source  VARCHAR(50)  NOT NULL,          -- 'chat', 'airflow', 'manual'
    trigger_input   JSONB,                           -- raw input: {industry, location, count, user_message}

    -- what the run is targeting
    target_industry VARCHAR(100),
    target_location VARCHAR(200),
    target_count    INTEGER,

    -- lifecycle
    status          VARCHAR(50)  NOT NULL DEFAULT 'started',
    -- allowed values:
    --   started | scout_running | scout_complete
    --   analyst_running | analyst_awaiting_approval | analyst_complete
    --   writer_running  | writer_awaiting_approval  | writer_complete
    --   outreach_running | outreach_complete
    --   completed | failed | cancelled

    current_stage   VARCHAR(50),
    -- allowed values: scout | analyst | writer | outreach | tracker | done

    -- output counters (updated as run progresses)
    companies_found         INTEGER NOT NULL DEFAULT 0,
    companies_scored        INTEGER NOT NULL DEFAULT 0,
    companies_approved      INTEGER NOT NULL DEFAULT 0,
    drafts_created          INTEGER NOT NULL DEFAULT 0,
    emails_sent             INTEGER NOT NULL DEFAULT 0,

    -- policy
    max_retries     INTEGER NOT NULL DEFAULT 3,
    retry_count     INTEGER NOT NULL DEFAULT 0,

    -- error tracking
    error_message   TEXT,

    -- timestamps
    started_at      TIMESTAMP NOT NULL DEFAULT NOW(),
    completed_at    TIMESTAMP,
    created_at      TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_agent_runs_status
    ON agent_runs (status);

CREATE INDEX IF NOT EXISTS idx_agent_runs_trigger_source
    ON agent_runs (trigger_source);

CREATE INDEX IF NOT EXISTS idx_agent_runs_started_at
    ON agent_runs (started_at DESC);
