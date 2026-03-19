-- Creates human_approval_requests table.
-- Tracks pending human-in-the-loop approval steps in the pipeline.
-- When Analyst finishes scoring OR Writer finishes drafts, a row is inserted here.
-- The system sends an email notification to the reviewer.
-- The pipeline pauses until status = 'approved' or the row expires.
-- Note: lead_scores and email_drafts already have approved_human columns for
--       individual item approvals. This table tracks the notification and
--       queue-level approval for a batch.
-- Dependencies: agent_runs (008).

CREATE TABLE IF NOT EXISTS human_approval_requests (
    id                      UUID        PRIMARY KEY DEFAULT gen_random_uuid(),

    run_id                  UUID        REFERENCES agent_runs(id) ON DELETE SET NULL,

    -- what needs approval
    approval_type           VARCHAR(50) NOT NULL,
    -- allowed values: 'leads' | 'emails'

    -- current state
    status                  VARCHAR(50) NOT NULL DEFAULT 'pending',
    -- allowed values: pending | approved | rejected | expired

    -- summary sent to the reviewer
    items_count             INTEGER,             -- how many leads or drafts are waiting
    items_summary           TEXT,                -- brief text describing what is waiting

    -- notification tracking (email only, no Slack)
    notification_email      VARCHAR(200),        -- who to notify
    notification_sent       BOOLEAN     NOT NULL DEFAULT FALSE,
    notification_sent_at    TIMESTAMP,

    -- approval response
    approved_by             VARCHAR(100),
    approved_at             TIMESTAMP,
    rejection_reason        TEXT,

    -- expiry: if not approved within this time the run may auto-cancel or escalate
    expires_at              TIMESTAMP,

    created_at              TIMESTAMP   NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_human_approval_requests_run_id
    ON human_approval_requests (run_id);

CREATE INDEX IF NOT EXISTS idx_human_approval_requests_status
    ON human_approval_requests (status);

CREATE INDEX IF NOT EXISTS idx_human_approval_requests_approval_type
    ON human_approval_requests (approval_type);
