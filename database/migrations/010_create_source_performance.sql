-- Creates source_performance table.
-- Learning memory for Scout agent.
-- After every Scout run, this table is updated with how well each source performed
-- for a given industry + location combination.
-- On the next Scout run for the same context, this table is read to rank sources
-- and start with the best-performing one first.
-- Dependencies: pgcrypto extension.

CREATE TABLE IF NOT EXISTS source_performance (
    id                      UUID    PRIMARY KEY DEFAULT gen_random_uuid(),

    -- identity: what source, for what context
    source_name             VARCHAR(200) NOT NULL,  -- e.g. 'yellow_pages', 'tavily', 'google_maps', 'yelp'
    industry                VARCHAR(100) NOT NULL,
    location                VARCHAR(200) NOT NULL,

    -- performance counters (cumulative across all runs)
    total_runs              INTEGER NOT NULL DEFAULT 0,
    total_leads_found       INTEGER NOT NULL DEFAULT 0,
    total_leads_passed      INTEGER NOT NULL DEFAULT 0,  -- passed Scout quality threshold

    -- quality scores
    avg_quality_score       FLOAT   NOT NULL DEFAULT 0.0,  -- rolling average 0.0–10.0
    last_quality_score      FLOAT,                          -- score from most recent run

    -- recency
    last_run_at             TIMESTAMP,

    created_at              TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMP NOT NULL DEFAULT NOW(),

    UNIQUE (source_name, industry, location)
);

CREATE INDEX IF NOT EXISTS idx_source_performance_context
    ON source_performance (industry, location);

CREATE INDEX IF NOT EXISTS idx_source_performance_avg_quality
    ON source_performance (avg_quality_score DESC);
