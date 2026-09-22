# QA remediation plan

Based on [QA_AUDIT.md](QA_AUDIT.md). Implement in the order below, with each step delivered as a reviewable change. The backend findings first need regression reproductions against an isolated database; current audit evidence is source review.

## 1. Establish a reliable verification environment — QA-06, QA-07

Tasks:

- Provision an isolated test PostgreSQL/pgvector database, Redis, and S3 substitute; install the backend's declared dependencies in a virtual environment or test container. Never point the suite at production: its fixtures clear Redis keys and create/delete database records.
- Apply Alembic migrations and run the existing backend suite to record the baseline before application changes.
- Reproduce the auth-store failures on the Node version used by CI and the current local version. Determine whether storage globals, jsdom configuration, or runtime compatibility causes the failure before changing setup.
- Align the documented, local, and CI Node versions. Configure a valid jsdom origin/storage environment if needed; keep the real credential-storage assertions intact.
- Read the installed Next.js guidance and configure ESLint directly using the installed compatible configuration. Replace `next lint`, exclude generated output, and add `npm run lint` to CI.
- Fix existing lint violations without blanket rule suppression. Update setup instructions with exact test commands and prerequisites.

Acceptance:

- Backend tests collect and run; baseline failures are recorded separately from remediation regressions.
- All 37 existing frontend tests pass, including all five auth-store assertions.
- Lint, type checking, and production build pass. A temporary intentional violation demonstrates that lint exits nonzero; remove the violation afterward.

## 2. Close the requirement ownership boundary — QA-01

Primary files: `backend/app/services/workspace_service.py`, `backend/app/api/v1/workspace.py`, `backend/app/models/contract.py`, backend workspace tests.

Tasks:

- Add failing integration tests using two real users and separately owned RFPs.
- Validate supplied requirement IDs as UUIDs at the request boundary.
- In the service transaction, verify that a mapped requirement belongs to the proposal's linked RFP and the authenticated tenant before inserting a section. Preserve support for an explicitly unmapped section.
- Return a consistent not-found response for nonexistent or unauthorized requirement references, without revealing ownership.
- Apply the same relationship check when resolving requirement text for regeneration so pre-existing invalid links cannot bypass the new create check.
- Audit existing section-to-requirement links with a read-only query. Produce a remediation list for invalid links; do not silently delete user content. Define and review a repair migration if any exist.

Acceptance:

- A valid mapped section and an unmapped section can be created.
- Another tenant's requirement, another RFP's requirement from the same tenant, and a missing requirement are rejected without inserting a section.
- Malformed IDs return validation errors rather than database exceptions.
- Regenerating a pre-existing invalid link fails before retrieval or an LLM call receives the requirement text.

## 3. Restore consistent evidence and section metadata — QA-03, QA-05

Primary files: `backend/app/services/draft_writer.py`, `backend/app/services/workspace_service.py`, `backend/app/api/v1/workspace.py`, retrieval/workspace tests.

Tasks:

- Add a proposal scope parameter to the single-section draft helper and pass it into retrieval.
- For generation, use the proposal already authorized by the route. For regeneration, derive it from the owned section; never trust an independent client-supplied proposal ID.
- Keep bid evidence priority and library fallback consistent with full-proposal drafting. Review helper call sites to avoid accidental unscoped calls.
- Include confidence and citation fields in the section detail query. Share a projection where practical, with explicit SQL aliases for joined tables.

Acceptance:

- Generation and regeneration retrieve relevant evidence attached only to the current bid.
- Evidence belonging to another proposal or tenant is excluded; library fallback still works.
- Detail and list endpoints return the same stored confidence and citations, including after regeneration and cache invalidation.

## 4. Make full drafting revision-aware and idempotent — QA-02

Primary files: drafting API, `backend/app/agent/drafting_agent.py`, `backend/app/worker/tasks.py`, section persistence/readers, Alembic migrations, frontend drafting controls.

Recommended behavior: one active drafting run per proposal. A successful redraft replaces the previous generated revision; manual, edited, and approved work remains protected. Failed runs leave the last usable proposal intact.

Tasks:

- Introduce persisted drafting-run identity and lifecycle. Enforce one active run with a database constraint or transactional lock, rather than a frontend-only check.
- Claim the run atomically in the API. Return a clear conflict for overlapping requests; accept an idempotency key so replaying the same request resolves to the same run.
- Pass the stable run ID to the worker. Make section persistence idempotent using a unique run/outline-position key; worker retries must not create new active sections.
- Stage generated output by run. Atomically publish the completed run and update proposal status only if that run still owns the active claim.
- Track section provenance and user edits explicitly. Do not guess that a section is safe to replace from its title. Snapshot the proposal revision at run start and detect edits made during generation; surface conflicts instead of overwriting them.
- Ensure workspace, compliance, export, counts, and cache keys consistently resolve the active revision and preserved work. Keep historical revisions out of the current export.
- Handle partial section failures explicitly: publish only according to the existing review policy, flag incomplete output, and never silently present a partial run as complete.
- Plan a migration for existing sections. Preserve ambiguous historical/manual records for review instead of automatically deduplicating by title.

Acceptance:

- Two simultaneous draft requests produce one active run.
- Retried tasks persist each output section once; a late worker cannot overwrite a newer run's status.
- Two completed full drafts expose one current generated revision, without accumulating duplicate outlines.
- Approved/manual/edited content survives a redraft; concurrent edits produce an explicit conflict.
- A failed run leaves the prior usable revision visible and exportable.

## 5. Make queue handoff durable — QA-04

Primary files: document, drafting, and export APIs; worker tasks; job services; Alembic migrations; polling UI; deployment configuration.

Recommended approach: a transactional outbox. A job and its pending dispatch record commit together; a separate dispatcher retries publication. This covers process crashes between database commit and broker publication as well as immediate broker errors.

Tasks:

- Introduce an outbox table with stable job IDs, attempt counts, next-attempt time, and dispatch/error state.
- Persist domain state and the outbox record in the same database transaction. Refactor service boundaries where separate commits currently prevent this.
- Run a supervised dispatcher with bounded retry/backoff and safe concurrent claiming. Publication is at least once, so all affected workers must deduplicate by stable job ID.
- Extend idempotency beyond drafting to export, ingestion, and reanalysis. Replayed HTTP requests must not create duplicate jobs or proposals.
- Account separately for upload storage: validate metadata before upload, and add compensation or orphan cleanup for objects whose database transaction fails. S3 is outside the database transaction.
- Distinguish queued, running, and failed/retryable states in API responses and UI. Document what a successful 202 guarantees: durable acceptance, not worker execution.
- Add bounded stale-job recovery using leases/heartbeats or equivalent ownership checks. Do not retry a healthy long-running LLM task solely because it is slow.
- Monitor aged outbox entries and failed dispatches; document dispatcher startup and recovery.

Acceptance:

- Broker outage leaves durable, recoverable queued work with an accurate UI state.
- Restoring the broker dispatches the original job without duplicate application results.
- Simulate crashes before publish, after publish but before acknowledgement, and during worker execution; recovery is safe in each case.
- Repeated uploads/exports with the same idempotency key resolve to the original result.
- Exhausted retries surface an actionable failure instead of indefinite progress.

Dependency: reuse step 4's drafting run identity and duplicate-execution safeguards. A short-term patch that catches publish errors and marks jobs failed can reduce confusion, but does not replace durable crash recovery.

## 6. Verify the complete workflow and release

Tasks:

- Add a browser integration test for upload → extraction → attach evidence → draft → edit/approve → regenerate → export/download. Use deterministic LLM fixtures for CI while exercising the real API, database, storage, and worker.
- Assert downloaded artifact contents, section order, preserved edits, and absence of obsolete duplicate sections; a successful download alone is insufficient.
- Run tenant-isolation and failure/retry tests at the API/worker level, alongside the existing authentication browser smoke test.
- Exercise migration upgrade and downgrade in an isolated database, including existing-section backfill. Validate deployment ordering and compatibility between API, worker, and schema versions.
- Run one controlled real-provider smoke test with a non-sensitive sample RFP to check actual extraction, grounding, and export quality. Keep provider-dependent checks separate from deterministic CI.
- Update `QA_AUDIT.md` with each finding's fix reference, verification evidence, and remaining limitations.

Release gate:

- All seven findings have passing regression evidence or an explicitly documented unresolved disposition.
- Lint, type checking, frontend tests/build, backend tests, migrations, and browser workflow checks pass.
- No unresolved tenant isolation, duplicate-run, lost-work, or permanently stuck-job defects remain.
- The dispatcher and worker recovery procedure have been exercised in the deployment-like test environment.

## Suggested change sequence

1. Test environment, Node compatibility, and lint repair.
2. Requirement authorization and invalid-link protection.
3. Proposal evidence propagation and section response consistency.
4. Draft revision schema, worker idempotency, and publication behavior.
5. Durable queue dispatch and upload/export/reanalysis recovery.
6. Full workflow regression coverage and release evidence.

This document is a plan only; no application fixes are applied by creating it.
