-- Alters companies table to support agentic run tracking.
-- Adds run_id: links each company to the specific run that discovered it.
-- Adds quality_score: raw quality score (0.0-10.0) assigned by Scout Critic.
-- Dependencies: agent_runs (008).

ALTER TABLE companies
    ADD COLUMN IF NOT EXISTS run_id       UUID  REFERENCES agent_runs(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS quality_score FLOAT;

CREATE INDEX IF NOT EXISTS idx_companies_run_id
    ON companies (run_id);

CREATE INDEX IF NOT EXISTS idx_companies_quality_score
    ON companies (quality_score DESC);
