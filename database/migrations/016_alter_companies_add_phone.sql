-- Migration 016: Add phone column to companies table
-- Stores the phone number scraped from Yellow Pages, Google Maps, or Yelp during Scout.
-- Used for the Call List feature — allows sales reps to call companies where email
-- contact enrichment returned nothing.
-- Format: raw string as returned by the source (e.g. "(716) 555-1234", "+17165551234")
-- NULL means no phone was found during scouting.

ALTER TABLE companies
  ADD COLUMN IF NOT EXISTS phone VARCHAR(30);
