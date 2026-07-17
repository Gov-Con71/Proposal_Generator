-- Sprint 8: persist the compliance critic's unresolved feedback on a section.
--
-- When the drafting agent exhausts its revision budget with the critic still
-- flagging gaps, the section is saved as needs_review. This column keeps the
-- critic's final feedback so a human reviewer can see *why* it needs review,
-- instead of that context being discarded.
--
-- Idempotent so it is safe to re-run against an existing database.

ALTER TABLE proposal_sections
    ADD COLUMN IF NOT EXISTS review_notes TEXT;
