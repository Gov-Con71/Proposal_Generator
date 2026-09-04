# ProposalAI — operational notes

AI-assisted RFP proposal drafting: ingest an RFP → extract requirements/compliance
matrix → retrieve relevant past-performance content (RAG) → draft each section
with an LLM, grounded and citation-tagged. See `README.md` for the product pitch,
`GAP_ANALYSIS.md`/`SPRINTS_OVERVIEW.md` for project history.

## Stack

FastAPI backend + Celery worker (`backend/`) + Next.js frontend
(`proposalai-frontend/`) + Postgres/pgvector + Redis + LocalStack (S3 stand-in).
Runs locally under **rootless Podman** via `podman compose` (a Docker Compose
CLI plugin talking to Podman's Docker-compatible API — not `podman-compose`).

Three compose files, pick one:
- `docker-compose.db.yml` — db/redis/localstack only, for running backend/frontend on the host.
- `docker-compose.yml` — backend + celery-worker + db/redis/localstack, no frontend container.
- `docker-compose.app.yml` — everything. `podman compose -f docker-compose.app.yml up --build -d`.

Copy `.env.example` to `.env` first (`cp .env.example .env`) and set a real
`GEMINI_API_KEY` or switch to Featherless (see below).

## Rootless Podman gotchas

These are baked into the compose files already — noted here so a from-scratch
investigation isn't needed again if something regresses:

- **Bind-mount ownership**: rootless Podman maps container UID 0 to the host
  user by default, so `appuser` (uid 1001 in `Dockerfile.backend`) only gets
  read access to the host-owned `./backend` bind mount, not write. Fixed via
  `userns_mode: "keep-id:uid=1001,gid=1001,size=65536"` on `backend` and
  `celery-worker`. The `size=65536` is load-bearing — omit it and published
  ports fail with `crun: write to /proc/sys/net/ipv4/ping_group_range ...
  Invalid argument` (too few IDs mapped for pasta's networking setup).
- **SELinux mount label**: `backend` and `celery-worker` both bind-mount
  `./backend`. Use `:z` (shared, lowercase), not `:Z` (private/exclusive) —
  `:Z` makes each container relabel the directory for itself only, so whichever
  container starts second silently locks the other out mid-run (surfaces as
  random `PermissionError` on hot-reload, *after* the first container looked
  fine at boot).
- **Known flaky race**: `podman compose ... up -d --force-recreate <svc1> <svc2>`
  occasionally hits `ping_group_range ... Invalid argument` on one of two
  containers recreated together, even with the mapping above — a pasta/network
  setup race, not a real config problem. Fix: `podman rm -f <container> &&
  podman compose -f <file> up -d <container>` to recreate it alone.

## Migrations

Alembic (`backend/migrations/`), 8 revisions on top of a squashed baseline.
`backend/init_scripts/*.sql` (mounted at Postgres's `docker-entrypoint-initdb.d`)
only gives a **fresh** container the schema as of migration `0001_baseline` — it
is frozen, not the source of truth (see `backend/init_scripts/README.md`). A
container that already has data does *not* get init_scripts re-run.

`backend/entrypoint.sh` runs `alembic upgrade head` before starting uvicorn,
gated by `RUN_MIGRATIONS=true` — set only on the `backend` service (not
`celery-worker`, which shares the same image/entrypoint) so exactly one process
migrates. `0001_baseline` is fully idempotent (`IF NOT EXISTS` throughout), so
this is safe to run against a freshly-initialized, already-migrated, or
never-touched-by-Alembic database alike.

`backend` has a `/health`-based healthcheck; `celery-worker` depends on
`backend: condition: service_healthy` — so on a fresh volume the worker won't
pick up a task before migrations have actually run.

## LLM provider

Swappable via `LLM_PROVIDER` (`gemini` | `featherless` | `openai_compatible`) —
`app/services/llm/`, dispatched through a registry (`_PROVIDER_FACTORIES` in
`llm/__init__.py`), not an if/elif chain — adding a provider that needs
genuinely new code is a one-line registration next to the others.
`openai_compatible` (`llm/openai_compatible.py`) needs no new code at all: set
`LLM_BASE_URL`/`LLM_API_KEY` to point at *any* OpenAI-compatible host —
OpenRouter, Together, a self-hosted vLLM/Ollama/LM Studio instance, etc.
`featherless` is just a preset of that same adapter (fixed base URL, reads
`FEATHERLESS_API_KEY`).

`get_llm(tier="default"|"light")`: `"light"` is for mechanical calls (HyDE query
generation, compliance/solicitation-matrix structuring) and uses `LLM_MODEL_LIGHT`
if set, else falls back to `LLM_MODEL` — tiering is opt-in, unset means no
behavior change. `LLM_PROVIDER_LIGHT` similarly overrides the *provider* for the
light tier only (e.g. a free/local backend for mechanical calls while the
default tier stays on a paid vendor) — same opt-in fallback. The final section
draft always uses the default tier's provider and model.

Every provider should implement `available_models()` (`llm/base.py`) so
`startup_checks.check_models()` can validate `LLM_MODEL`/`LLM_MODEL_LIGHT`
against the actual API key at boot instead of failing silently minutes later
inside a Celery task (see Diagnostics below) — this now covers both tiers, and
both `gemini` and the whole `openai_compatible` family (Featherless included)
implement it via each host's `/models` listing endpoint.

**Gemini free tier is 20 requests/day per model** — drafting fires several LLM
calls per section (HyDE + generation, per requirement), so it exhausts fast,
well within one proposal's worth of testing. When it's out, calls retry 5×
with ~59s backoff before failing, so a section takes ~5 min to error out — this
is what the frontend surfaces as "Drafting timed out," not an actual hang.
Check for `429 RESOURCE_EXHAUSTED` / `quotaId:
GenerateRequestsPerDayPerProjectPerModel-FreeTier` in celery-worker logs to
confirm. Fix: wait for the daily reset, enable billing on the key's Google
Cloud project, or switch to `LLM_PROVIDER=featherless` (flat-rate, no daily
cap — needs `FEATHERLESS_API_KEY`, `LLM_MODEL=Qwen/Qwen2.5-72B-Instruct`,
`EMBEDDING_MODEL=Qwen/Qwen3-Embedding-8B`).

HyDE narratives are cached in Redis (`hyde:<hash>`, `draft_writer.py`) keyed by
content hash of `(section_title, requirement_text)` — a retry storm regenerates
the draft, not the HyDE query, on every attempt after the first.

## Diagnostics — check these before tailing container logs

`backend/app/api/v1/monitoring.py` exposes, unauthenticated:
- `GET /health` — liveness.
- `GET /ready` — DB + Redis reachability, with a reason on failure (exception
  type only, not the message — the message can contain a connection string).
- `GET /metrics` — aggregated LLM cost/latency/error telemetry.

These usually answer "is it up / why not / is the LLM erroring" faster than
`podman logs`. When you do need logs, every request/task line carries a
`request_id` (and `rfp_id`/`proposal_id`/`task_id` where relevant) — grep by
that ID, or grep for `ERROR|Traceback` first, rather than tailing hundreds of
lines. Structured logging is `app/core/logging.py`; `LOG_FORMAT=console` in dev
is human-readable, `json` in production.

## Tests

`podman exec fastapi_backend_app python -m pytest tests/ -q` — runs against the
live compose stack's Postgres/Redis (not fully hermetic unit tests; fixtures in
`tests/conftest.py` flush Redis-backed state — rate-limit counters, HyDE cache —
around every test for isolation). 184 passing / 11 skipped as of this file's
last update.
