-- Creates email_win_rate table.
-- Learning memory for Writer agent.
-- Updated every time Tracker records an open or reply event.
-- Writer reads this table to pick the best-performing template for a given industry.
-- Dependencies: pgcrypto extension.

CREATE TABLE IF NOT EXISTS email_win_rate (
    id                      UUID    PRIMARY KEY DEFAULT gen_random_uuid(),

    -- identity: which template, for which industry
    template_id             VARCHAR(100) NOT NULL,  -- matches template_used in email_drafts
    industry                VARCHAR(100) NOT NULL,

    -- counters (cumulative)
    emails_sent             INTEGER NOT NULL DEFAULT 0,
    emails_opened           INTEGER NOT NULL DEFAULT 0,
    replies_received        INTEGER NOT NULL DEFAULT 0,
    positive_replies        INTEGER NOT NULL DEFAULT 0,  -- sentiment = 'positive'

    -- computed rates (updated after each event)
    open_rate               FLOAT   NOT NULL DEFAULT 0.0,
    reply_rate              FLOAT   NOT NULL DEFAULT 0.0,
    positive_reply_rate     FLOAT   NOT NULL DEFAULT 0.0,

    updated_at              TIMESTAMP NOT NULL DEFAULT NOW(),
    created_at              TIMESTAMP NOT NULL DEFAULT NOW(),

    UNIQUE (template_id, industry)
);

CREATE INDEX IF NOT EXISTS idx_email_win_rate_industry
    ON email_win_rate (industry);

CREATE INDEX IF NOT EXISTS idx_email_win_rate_reply_rate
    ON email_win_rate (reply_rate DESC);
