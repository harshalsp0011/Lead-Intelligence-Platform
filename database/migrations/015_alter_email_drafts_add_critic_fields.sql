-- Migration 015: Add Critic Loop fields to email_drafts table
-- Phase C: Writer + Critic Loop
--
-- critic_score:    0.0–10.0 — final score the Critic gave this draft
-- low_confidence:  true if draft never reached score >= 7 after 2 rewrites
-- rewrite_count:   0, 1, or 2 — how many times Writer rewrote before saving

ALTER TABLE email_drafts
  ADD COLUMN IF NOT EXISTS critic_score    FLOAT,
  ADD COLUMN IF NOT EXISTS low_confidence  BOOLEAN DEFAULT false,
  ADD COLUMN IF NOT EXISTS rewrite_count   INTEGER DEFAULT 0;
