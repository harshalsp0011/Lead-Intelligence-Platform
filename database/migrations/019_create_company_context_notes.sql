-- Creates company_context_notes table for storing manually entered meeting context.
-- Used by the CRM leads email flow to give the Writer agent context about
-- face-to-face discussions when company_features / lead_scores are not available.
--
-- notes_raw    : original free-text entered by the user
-- notes_formatted : LLM-structured bullet points (used by writer + critic)
-- source       : always 'manual_input' — distinguishes from pipeline-derived data
-- created_by   : username or identifier of who entered the notes

CREATE TABLE IF NOT EXISTS company_context_notes (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id      UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    notes_raw       TEXT,
    notes_formatted TEXT,
    source          VARCHAR(50) NOT NULL DEFAULT 'manual_input',
    created_by      VARCHAR(100),
    created_at      TIMESTAMP DEFAULT NOW(),
    updated_at      TIMESTAMP DEFAULT NOW()
);

-- One context record per company (upsert target)
CREATE UNIQUE INDEX IF NOT EXISTS idx_company_context_notes_company_id
    ON company_context_notes (company_id);
