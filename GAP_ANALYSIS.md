# ProposalAI — Gap Analysis

**Date:** 2026-07-17 · **Updated:** 2026-07-17 (items 1–4 resolved)
**Scope:** `backend/` (FastAPI + Celery + Postgres) and `proposalai-frontend/` (Next 16), branch `Document_Ingestion_Pipeline`.
**Method:** every gap below was reproduced against the running stack, not inferred from reading code. Evidence is quoted inline.

> **Status:** items 1–6 are fixed and verified — §3.1 (restart policy), §1.1
> (retired models), §2.1 (SSE tenant leak), §2.3 (login rate limiting), §1.2
> (id-space collision) and §4.1 (nothing created proposals), plus §1.3, a silent
> cache bug found while fixing §1.2.
>
> **The product now works end to end for the first time:** upload → ingest →
> extract → dashboard → workspace → compliance → RAG draft, verified in a
> browser. §1.1's original diagnosis was wrong and has been corrected in place.
>
> Remaining highest-priority item: **§3.2/§3.3, migrations in deploy** — required
> before any production launch.

---

## Summary

The architecture is sound. Tenant scoping is applied consistently at the service layer, the migrations are idempotent, error handling is deliberate, and the RAG/ingestion design is coherent. Sprints 1–8 built real, DB-backed features.

The gaps are not architectural. They cluster in three places:

1. **Two defects make the core product journey non-functional today** — one operational (Gemini quota), one a genuine bug (`proposal_id` vs `rfp_id`).
2. **The auth surface has holes that the recent auth work did not cover** — and one that Sprint 7 made worse.
3. **Production deployment would not work**, because nothing applies the schema to a real database.

Counts: **2 critical**, **5 security**, **4 operational**, **5 product/completeness**, **1 testing**.

---

## 1. Critical — the product does not currently function end to end

### 1.1 ~~The Gemini API key is out of quota~~ → **RESOLVED. Two retired models, not a billing problem.**

**Severity: Critical · Fixed 2026-07-17**

> **Correction.** The original diagnosis in this report — "the free tier is not
> enabled for the project, enable billing" — **was wrong.** Probing the API
> directly disproved it: the key is valid (`ListModels` → 200) and other models
> answer fine. The `limit: 0` was per-model, not per-project.

The real cause was two stale model names in config:

| Setting | Was | Result | Now |
|---|---|---|---|
| `LLM_MODEL` | `gemini-2.0-flash` | **429**, `limit: 0` — listed but carries no free-tier request quota | `gemini-2.5-flash` (**200**) |
| `EMBEDDING_MODEL` | `text-embedding-004` | **404** — retired, absent from `ListModels` | `gemini-embedding-001` |

The embedding model had been broken independently of the quota issue, which
means the RAG layer could never have worked either.

**The dimension trap.** `gemini-embedding-001` returns **3072** dims by default;
`historical_chunks.embedding` is `vector(768)`, so a naive swap fails every
insert. The adapter never forwarded its `embed_dim`. It now sends
`output_dimensionality=768`. Gemini only pre-normalises at the full 3072 dims —
a truncated 768-dim vector comes back with ‖v‖ ≈ 0.59 — so the adapter
normalises. Retrieval uses cosine (`<=>`), which is magnitude-invariant and was
never at risk, but unit vectors match the vendor's guidance and stop a future
switch to inner-product (`<#>`) from silently skewing scores.

**Verified end to end** after the change: a real RFP ingested `completed` with 5
requirements extracted, the compliance matrix built from them, a past-performance
chunk embedded and stored (768 dims, ‖v‖ = 1.0000), and RAG drafting produced a
section grounded in the retrieved contract number. This is the first time the
pipeline has run green.

**Still open (adjacent).** `document_service` marks a document `failed` but
stores no reason, so the UI cannot distinguish "model retired" from "corrupt
PDF". This gap is exactly why a config typo presented as a dead product. A
`failure_reason` column would surface it without reading worker logs.

**Note on model pinning.** Both names are now pinned in `config.py`,
`.env.example`, and both compose files. Models get retired; a startup check that
the configured models resolve via `ListModels` would turn a silent 404 into a
loud boot failure.

---

### 1.2 ~~`proposal_id` and `rfp_id` are different keys sharing one URL namespace~~ → **RESOLVED**

**Severity: Critical · Fixed 2026-07-17**

> **Decision: the proposal is the aggregate.** The whole `/proposals/{id}/…`
> namespace now takes a **proposal id**, matching what exports, integrity and the
> dashboard already did. `proposals_service.rfp_for_proposal()` is the single
> seam that resolves it to the underlying document; no route knows about both.
>
> `POST /documents/upload` now creates the proposal (this also closes **§4.1** —
> nothing created proposals before, so the dashboard was structurally empty).
> It returns both `proposalId` (what the client navigates by) and `rfpId`.
>
> `Requirement.proposalId` / `ProposalSection.proposalId` actually carried an
> **rfp_id** — the confusion in miniature. Renamed to `documentId`, matching the
> existing `Proposal.documentId` convention. Nothing read them, and the
> contract-drift test now holds both sides together.
>
> **Verified in a browser:** dashboard shows `TOTAL PROPOSALS: 1`, and its own
> link opens a workspace listing all 3 extracted requirements. The compliance
> matrix renders them. Passing an `rfp_id` where a proposal id belongs is now a
> clean 404 — one id space, unambiguous.
>
> A proposal with no linked RFP returns **409**, not 404: it exists, it just has
> no document yet.
>
> **Follow-up (deeper modelling issue, not fixed):** `proposal_sections.rfp_id`
> means sections belong to the *document*, so two proposals answering one RFP
> would silently share drafted sections. Re-keying sections to `proposal_id` is a
> schema + data migration, tracked separately.

<details>
<summary>Original finding</summary>

`proposals` and `rfp_documents` are separate tables with separate primary keys; `proposals.rfp_id` is a nullable FK (`init_scripts/sprint6_proposals.sql`). But `/proposals/{id}/…` means **different things depending on the suffix**:

| Route | Keyed by |
|---|---|
| `GET /proposals/{proposal_id}` | `proposals.proposal_id` |
| `GET /proposals/{proposal_id}/integrity` | `proposals.proposal_id` |
| `GET /proposals/{rfp_id}/requirements` | `rfp_documents.rfp_id` |
| `GET /proposals/{rfp_id}/sections` | `rfp_documents.rfp_id` |
| `GET /proposals/{rfp_id}/compliance` | `rfp_documents.rfp_id` |

The dashboard renders `/proposals/${p.id}/workspace` where `p.id` is a **proposal_id** (`app/(app)/dashboard/page.tsx:90`). The workspace then calls `useRequirements(id)` with that same id, hitting a route keyed by **rfp_id**.

Reproduced with one tenant owning a proposal linked to its RFP:

```
proposal_id = 11ae6f2b-947b-469c-bbb2-d9adad403044
rfp_id      = a88682ed-11a6-4f1f-8737-8819161f13cf

GET /proposals/<proposal_id>/requirements -> 404  {"detail":"Not found."}
GET /proposals/<rfp_id>/requirements      -> 200  [{...}]
```

**Impact.** The moment a proposal exists, clicking it from the dashboard opens a workspace that cannot find its own requirements. This is masked right now only because **nothing creates proposals** (see 4.1), so the dashboard is permanently empty. Fixing 4.1 without fixing this converts an empty dashboard into a broken one.

**Fix.** Pick one identifier for the URL space. Recommended: key everything on `proposal_id` and have the workspace/compliance/sections services resolve `proposal.rfp_id` internally. That matches the domain (a proposal is the thing a user works on; the RFP is an input) and leaves the frontend's existing links correct. Rename the route params so the collision cannot recur.

</details>

### 1.3 The ingestion worker could never invalidate the cache — found while fixing §1.2

**Severity: High · Fixed 2026-07-17 · Pre-existing, silent**

Surfaced by driving the real flow: after a *successful* extraction the workspace
still showed zero requirements, while `/documents/{rfp}` reported the true count.
The rows were in the database the whole time — the API was serving a **stale
cached empty list**.

Two independent faults, both invisible:

1. **The worker never invalidated anything.** The API caches requirements and
   compliance per `(tenant, rfp)` on read, and the process page polls *while*
   ingestion runs — so an empty list is almost always cached microseconds before
   the worker inserts. The API invalidates on its own mutations, but the worker
   writes straight to the DB and evicted nothing.
2. **The worker had no `CACHE_URL`.** It fell back to `redis://localhost:6379/2`
   — itself, not the Redis service. `core/cache.py` fails open by design, so the
   connection error was swallowed at debug level. The worker had **never** been
   able to touch the cache, and nothing said so.

The second is a good illustration of the cost of failing open: a total
misconfiguration produced no error, just quietly degraded behaviour. Fixed by
evicting at the end of `run_ingestion` and passing `CACHE_URL` to the worker in
both compose files.

**Verified:** polling during ingestion (as the UI does), requirements are now
visible the instant it completes rather than after a 60s TTL.

**Follow-up.** The same blind spot applies to the `draft_proposal` worker task,
which writes sections without eviction. Worth auditing every worker write against
the cache keys the API owns.

---

## 2. Security

### 2.1 ~~The SSE pipeline stream serves any anonymous caller~~ → **RESOLVED**

**Severity: High · Fixed 2026-07-17**

> The token is now **required** (401 without one, 401 if invalid), and the
> ownership check is unconditional. A document belonging to another tenant now
> returns a frame byte-identical to a genuinely missing one, so the stream is no
> longer an existence oracle for other tenants' `rfp_id`s. Re-verified live:
> anonymous → 401; tenant B → "Document not found."; owner → real progress.
> Covered by `test_stream_requires_a_token` and
> `test_stream_hides_another_tenants_document`.
>
> §2.2 below (token in the query string) remains open.

<details>
<summary>Original finding</summary>

`app/api/v1/pipeline.py:128`:

```python
if user_id is not None and owner is not None and owner != user_id:
    return
```

When no token is supplied, `user_id is None` and the ownership check is skipped. The docstring states the intent: *"without one it still streams status (the rfp_id acts as the capability)"*.

Demonstrated against another tenant's document:

```
1. no token at all      -> data: {"proposalId":"36b5a8c7-…","status":"running","overallProgress":20,…}
2. a DIFFERENT tenant's valid token -> (empty — correctly blocked)
3. GET /proposals/<rfp>/requirements, no auth -> 401
```

**Authenticating makes you less privileged**: present tenant B's token and you are blocked; present nothing and you get the data. Every other route in the API returns 401 without a token.

**Impact.** Leaks ingestion progress, filename-derived step descriptions, and existence/status of another tenant's document to anyone with the `rfp_id`. The id is a UUID, so this is security-by-obscurity — and the id is not secret: it sits in the URL bar (`/proposals/new/process?rfp=<id>`), browser history, and `Referer` headers.

**Fix.** Require a valid token and a matching owner. Treat "no token" as 401, exactly like every sibling route.

</details>

### 2.2 The access token is passed in the URL query string

**Severity: Medium · By design, needs a different design**

`GET /proposals/{rfp_id}/pipeline/stream?token=<JWT>`. The comment is honest about why — `EventSource` cannot set headers — but the consequence is that a bearer token lands in server access logs, browser history, and any proxy in between.

**Fix.** Either issue a short-lived single-purpose stream ticket instead of the session JWT, or move to `fetch()` + `ReadableStream` (which supports headers), or send the token in a cookie the stream endpoint reads.

### 2.3 ~~No rate limiting on authentication~~ → **RESOLVED for login**

**Severity: High · Fixed 2026-07-17**

Before — twenty rapid failed logins, all answered normally, no `429` anywhere:

```
401 401 401 401 401 401 401 401 401 401 401 401 401 401 401 401 401 401 401 401
```

After — the same twenty requests:

```
401 401 401 401 401 401 401 401 401 401 429 429 429 429 429 429 429 429 429 429
                                        └─ Retry-After: 896
```

`core/rate_limit.py` adds fixed-window counters on the Redis the cache already
uses (no new dependency; shared across replicas, unlike an in-process limiter).
Two deliberate properties, both covered by tests:

* **Only failures count.** A correct password never consumes budget, so a
  legitimate user is never throttled — and an attacker cannot lock a victim out
  of their own account by deliberately failing. A successful login clears the
  counter.
* **Per-account is the primary control** (10 failures / 15 min), because a
  rotating botnet evades per-IP limits, and a misconfigured proxy would collapse
  every caller into one IP bucket. Per-IP (50 / 15 min) is secondary and higher,
  since an office NAT legitimately shares an address.

Once throttled, even the *correct* password is refused — an attacker who
eventually guesses right still gets a 429.

**Fails open** if Redis is unreachable, matching `core/cache.py`: a Redis blip
must not lock every user out of the product. The trade-off is explicit and
logged at WARNING.

**Still open.** `/auth/register` is unlimited, so mass account creation and
enumeration remain possible. An arbitrary per-IP cap there would break the test
suite and legitimate shared-IP signups; this is better solved at the edge with a
CAPTCHA or WAF rule than with a counter.

**Deployment note.** `rate_limit.client_ip()` reads `request.client.host`, which
is only the real caller when uvicorn runs with `--proxy-headers` behind a trusted
proxy. Without it every request appears to come from the load balancer and shares
one IP bucket — which is why the per-account limit carries the weight.

### 2.4 No password policy

**Severity: Medium · Confirmed**

```
register with password 'x' -> HTTP 201
```

`RegisterRequest.password` is an unconstrained `str`. A one-character password is accepted.

**Fix.** A minimum length (NIST suggests ≥8 and screening against breached-password lists; complexity rules are not recommended). One `Field(min_length=…)` plus a denylist check.

### 2.5 Tokens live in `localStorage` and a non-HttpOnly cookie — and Sprint 7 widened the blast radius

**Severity: High · Confirmed**

The Zustand store persists to `localStorage`, and the route-guard cookie is set from JavaScript with no flags:

```js
document.cookie = `proposalai-token=${session.accessToken}; path=/`   // no HttpOnly, Secure, SameSite
```

Any XSS on the page reads both.

**This one is on the recent work.** Sprint 7 added a 30-day refresh token and persisted it in the same `localStorage`. Before, stealing a token bought an attacker ≤24h. Now it buys a **rotatable 30-day session**. Rotation with reuse detection limits *concurrent* misuse — an attacker who rotates gets detected when the real client next refreshes — but it does not help if the attacker simply keeps rotating and the victim never returns.

**Fix.** Move the refresh token to an `HttpOnly; Secure; SameSite=Strict` cookie so JavaScript cannot read it, and keep only the short-lived access token in memory (not `localStorage`). At minimum add `Secure; SameSite=Strict` to the existing cookie.

---

## 3. Operational / deployment

### 3.1 ~~The backend is the only service with no restart policy~~ → **RESOLVED**

**Severity: High · Fixed 2026-07-17 · Root cause of a real incident**

| Service | `restart:` was | now |
|---|---|---|
| db, redis, localstack, celery-worker | `always` | unchanged |
| frontend | `unless-stopped` | unchanged |
| **backend** | **none** | **`unless-stopped`** |

This is exactly why the API sat `Exited (255)` for two days while every other
container stayed `Up`, and why the symptom presented as "can't create new users".
The frontend was healthy and served mock data over a dead API, so the failure was
invisible.

Demonstrated with two throwaway containers that crash identically:

```
no policy       -> status: exited      restarts: 0   ← the backend, until now
unless-stopped  -> status: restarting  restarts: 5
```

`unless-stopped` rather than `always` so a deliberate `docker compose stop` is
still respected across a daemon restart.

### 3.2 Deployment never applies the database schema

**Severity: Critical for launch · Confirmed**

`.github/workflows/deploy.yml` builds the backend image, pushes to ECR, and deploys the frontend to Vercel. It contains **no migration step** — no `psql`, no `alembic`, no reference to `init_scripts/`.

`init_scripts/` is only mounted at `docker-entrypoint-initdb.d`, which Postgres runs **once, on first initialisation of an empty data directory**. A managed RDS instance never runs it.

**Impact.** A production database would have no `users`, no `proposals`, no `company_profiles`, no `refresh_tokens`. The service would boot (config defaults let it) and fail on first request.

**Fix.** Add a migration step to the deploy job, and adopt a real migration tool (below).

### 3.3 There is no migration tool — only first-boot SQL

**Severity: Medium (compounding)**

Schema changes are idempotent `.sql` files applied alphabetically. This works for a fresh container and is well written, but it has no notion of *applied state*: nothing records which migrations ran, nothing can roll back, and drift between environments is undetectable. I had to apply `sprint7_auth.sql` to the running dev database by hand — a step easy to forget and impossible to audit.

**Fix.** Adopt Alembic (or similar) and import the existing scripts as the baseline revision. The idempotent style means this can be done without a flag day.

### 3.4 No healthcheck or `depends_on` condition for the backend

**Severity: Low**

`db` and `redis` define healthchecks; `backend` does not. `frontend` declares `depends_on: [backend]` with no condition, so it starts against a backend that may not be listening. `GET /health` and `/ready` already exist and are ideal for this.

---

## 4. Product completeness

### 4.1 Nothing creates a proposal, so the dashboard can only ever be empty

**Severity: High · Confirmed**

`POST /proposals` exists and works. No frontend code calls it — the only reference to `proposalsApi.create` is its own definition. The upload flow creates an `rfp_documents` row and goes straight to the workspace, never creating the `proposals` row that the dashboard lists.

**Impact.** The dashboard, the archive, and every derived metric are structurally empty regardless of user activity. Combined with 1.2, the fix is not "call create" — it needs the identifier question settled first.

### 4.2 The upload metadata form is decorative

**Severity: Medium · Confirmed**

`app/(app)/proposals/new/page.tsx` collects Title, Agency, Solicitation #, Deadline, Contract type, NAICS — and never sends them. `POST /documents/upload` accepts the file only. Users type data that is silently discarded. (Sprint 6 cleared the fabricated defaults and left a note; wiring it needs a contract change — most likely resolved by 4.1, since these fields map onto the `proposals` table.)

### 4.3 The Security page's password change does nothing

**Severity: Medium · Confirmed**

`app/(app)/security/page.tsx` renders Current/New/Confirm password inputs and makes zero API calls. There is no change-password endpoint. The form cannot work.

### 4.4 `users.is_active` is enforced but unreachable

`authenticate()` honours `is_active`, but nothing can set it — no admin endpoint, no UI. Deactivation is a manual `UPDATE`. The same is true of the `admin` role: `require_role("admin")` exists but no route uses it and nothing can promote a user.

### 4.5 Templates and Calculators are static mockups

Both are linked in the primary sidebar and make no API calls. They present as features. Not defects, but they set an expectation the backend does not meet.

---

## 5. Testing

### 5.1 The frontend has no tests at all

**Severity: Medium · Confirmed**

No test script, no framework, no test directory in `proposalai-frontend`. CI runs `tsc --noEmit` and `next build` only. Typecheck cannot catch what actually broke here: an interceptor that hijacks a failed login, a hook querying `undefined`, an empty state that never renders.

The backend is in good shape by comparison — 43 tests covering auth, tenancy, ingestion, exports, and RAG, plus a contract-drift guard.

**Fix.** Vitest + Testing Library for hooks/stores (the `client.ts` interceptor and `useProcessing` are the highest-value targets), and one Playwright smoke test for login → upload → workspace.

---

## Recommended order

The sequencing matters more than the list — several of these interlock.

| # | Gap | Status |
|---|---|---|
| 1 | 3.1 backend `restart:` | ✅ **Done** — `unless-stopped` in both compose files. |
| 2 | 1.1 retired models | ✅ **Done** — pipeline verified green end to end. |
| 3 | 2.1 SSE anonymous access | ✅ **Done** — token required, foreign docs indistinguishable from missing. |
| 4 | 2.3 auth rate limiting | ✅ **Done** for login; `/auth/register` still open. |
| 5 | 1.2 id-space collision | ✅ **Done** — proposal is the aggregate; one id space. |
| 6 | 4.1 proposal creation | ✅ **Done** — upload creates it; dashboard is real. |
| — | 1.3 worker cache eviction | ✅ **Done** — found while verifying 1.2. |
| 7 | 3.2 + 3.3 migrations in deploy | **Next.** Required before any production launch. |
| 8 | 2.5 token storage | Design change; do it deliberately, not under time pressure. |
| 9 | 5.1 frontend tests | Locks in everything above. |
| — | 4.2 upload metadata form | Now unblocked: the fields map onto the proposal §1.2 creates. |

### Open follow-ups

* **Sections belong to the document, not the proposal** (`proposal_sections.rfp_id`).
  Two proposals answering one RFP would silently share drafted sections. Schema +
  data migration; see §1.2.
* **Audit every worker write against the API's cache keys.** `draft_proposal`
  writes sections without eviction — the same class of bug as §1.3.
* **Model resolution is unchecked at boot.** A retired model name (§1.1) took the
  whole product down and presented as a quota problem. Validating the configured
  models against `ListModels` at startup would make this loud and immediate.
* **`aiConfidenceScore` and `referenceTags` are not populated** on generated
  sections (observed `0.0` and `[]` on a real RAG draft), so the workspace's
  confidence and citation UI has nothing to render.
* **Requirement categorisation is coarse** — all five requirements from a varied
  test RFP (scope, parts, testing, packaging) came back `technical`, which will
  make the compliance matrix's category grouping near-useless.
* **`/auth/register` rate limiting** — see §2.3.
* **Fail-open is load-bearing and untested.** §1.3 showed a total cache
  misconfiguration producing no error at all. Worth a startup log line stating
  whether the cache is reachable, so "degraded" is visible rather than silent.
