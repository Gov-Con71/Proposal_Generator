# QA audit — 2026-09-07

Release assessment: hold production sign-off until the tenant-boundary defect is fixed and the core workflow is exercised against an isolated running stack.

Scope: repository review of authentication, document upload, drafting, retrieval, section CRUD, export queuing, and test configuration; local frontend checks. Backend findings below are source-confirmed paths, not live exploit reproductions.

## Findings

### QA-01 — High: section creation accepts another tenant's requirement

`backend/app/services/workspace_service.py:289–306` checks ownership of the proposal but inserts the supplied `requirement_id` without checking its document or owner. The database foreign key validates existence only. `requirement_text_for_section` (line 369) subsequently reads the linked requirement without a tenant constraint, and the regenerate endpoint passes that text into generation.

Reproduction to add: create users A/B and a requirement owned by B; as A, create a section in A's proposal with B's requirement ID, then regenerate it. The current path accepts the link and uses B's text. This requires knowledge of the other requirement UUID; UUID secrecy is not authorization.

Fix: validate that the requirement belongs to the proposal's linked RFP and current tenant before inserting. Test both another tenant's requirement and another RFP belonging to the same tenant; reject without creating a row.

### QA-02 — High: repeat full drafts append duplicate sections

`backend/app/api/v1/workspace.py:draft_proposal` permits repeat/concurrent requests. `backend/app/agent/drafting_agent.py:run_drafting` starts a fresh outline each time, and its save path (around line 898) calls `insert_proposal_section`, which always creates a fresh UUID and INSERT. No run replacement or active-run filter is applied when listing sections.

Impact: drafting twice accumulates both outlines; overlapping jobs can mix sections and report completion while another job remains active.

Fix: define revision semantics, atomically reject overlapping runs, and publish one completed revision at a time while preserving approved/manual work. Verify repeated requests and retries do not duplicate the active proposal.

### QA-03 — Medium: section generation ignores proposal evidence

`backend/app/services/draft_writer.py:586` calls `search_similar` without `proposal_id`. Both single-section generation and regeneration in `backend/app/api/v1/workspace.py` use this helper. `retrieval.py:205` and its scope predicate establish that omission searches only the long-term library, excluding bid attachments.

Impact: a full draft can use attached evidence, but regenerating a section loses that evidence and may produce an ungrounded response.

Fix: propagate the authorized proposal ID through the helper. Verify a bid-only document is retrieved and another proposal's evidence is excluded.

### QA-04 — Medium: queue failures leave persistent jobs stuck

The document upload/reanalysis, full-draft, and export routes persist pending/drafting state before calling `celery_app.send_task`, without compensating on publish failure. See `backend/app/api/v1/documents.py`, `workspace.py:draft_proposal`, and `exports.py:create_export`.

Impact: a broker outage returns an error after persistence, leaving work pending with no worker message; retrying uploads/exports can create duplicates.

Fix: use a durable outbox/reconciliation path or record a recoverable enqueue-failed state. Inject a broker publish exception and assert the item reaches an actionable state rather than polling indefinitely.

### QA-05 — Medium: section detail silently drops confidence and citations

`backend/app/services/workspace_service.py:272–277` omits `ai_confidence_score` and `reference_tags` from `_section_row`. `get_section` passes that row to `_to_section`, which substitutes `0.0` and `[]`. The list endpoint selects both columns.

Impact: detail and list responses disagree for the same grounded section.

Fix: include the missing columns, ideally sharing the projection. Verify both endpoints preserve a stored nonzero confidence and citation list.

### QA-06 — Medium: documented lint check cannot run

Reproduced: `npm run lint` invokes `next lint` and exits 1 with `Invalid project directory provided .../proposalai-frontend/lint`. The script is in `proposalai-frontend/package.json:15`. CI does not run lint.

Fix: configure an ESLint CLI command compatible with the installed dependencies and add it to CI. Verify the command both runs successfully and rejects an intentional lint violation.

### QA-07 — Medium: auth-store tests fail before assertions locally

Reproduced on Node v26.8.1: `npm test` reports 32 passing and 5 failing tests. All five failures are at `proposalai-frontend/test/auth-store.test.ts:21`: `localStorage.clear()` encounters undefined storage. The credential and lifecycle assertions never execute.

This is a test/runtime compatibility failure, not proof of broken browser authentication. CI selects Node 24, while package engines accept this local Node version.

Fix: reproduce under the supported Node versions, configure jsdom storage/globals explicitly or narrow the supported runtime range, then rerun all credential assertions.

## Validation and limits

- Frontend type check: passed.
- Frontend unit tests: 32 passed, 5 failed during auth-store setup.
- Frontend lint: failed immediately as above.
- Production build: passed after retrying with network permission for Google Fonts. The initial sandboxed attempt could not fetch fonts.
- Backend collection: blocked by `ModuleNotFoundError: No module named 'psycopg2'` in the host environment.
- Container inspection: no running Podman containers. No live backend, database, queue, storage, or browser workflow results are claimed.
- Existing browser coverage is an authentication smoke test; the upload → extraction → draft → edit/approve → export journey still needs browser-level verification, including tenant isolation and worker failure/retry cases.
- No dependency vulnerability scan, load test, live LLM quality evaluation, or accessibility audit was performed.

Application source was not changed during this audit.
