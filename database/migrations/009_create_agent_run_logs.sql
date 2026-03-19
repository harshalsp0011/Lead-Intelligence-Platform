-- Creates agent_run_logs table.
-- Step-by-step audit log inside each run.
-- Every agent action writes one row: source tried, quality checked, lead scored,
-- draft created, email sent, critic decision, retry, etc.
-- Dependencies: agent_runs (008).

CREATE TABLE IF NOT EXISTS agent_run_logs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    run_id          UUID NOT NULL REFERENCES agent_runs(id) ON DELETE CASCADE,

    -- which agent and what it did
    agent           VARCHAR(50)  NOT NULL,
    -- allowed values: scout | analyst | writer | outreach | tracker | critic | orchestrator

    action          VARCHAR(100) NOT NULL,
    -- examples:
    --   scout:    source_attempted | quality_checked | company_saved | crawl_skipped
    --   analyst:  lead_scored | enrichment_called | tier_assigned
    --   writer:   draft_created | tone_validated | rewrite_triggered
    --   outreach: email_sent | followup_scheduled | daily_limit_hit
    --   tracker:  reply_detected | status_updated | approval_alert_sent
    --   critic:   quality_passed | quality_failed | retry_triggered

    status          VARCHAR(20)  NOT NULL,
    -- allowed values: success | failure | retry | skipped | waiting

    -- optional context
    input_summary   TEXT,        -- short description of what was passed in
    output_summary  TEXT,        -- short description of what came out
    quality_score   FLOAT,       -- critic quality score 0.0–10.0 if applicable
    retry_count     INTEGER      NOT NULL DEFAULT 0,
    duration_ms     INTEGER,     -- how long this action took
    error_message   TEXT,

    logged_at       TIMESTAMP    NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_agent_run_logs_run_id
    ON agent_run_logs (run_id);

CREATE INDEX IF NOT EXISTS idx_agent_run_logs_agent_action
    ON agent_run_logs (agent, action);

CREATE INDEX IF NOT EXISTS idx_agent_run_logs_status
    ON agent_run_logs (status);
