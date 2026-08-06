# Deployment & Operations Runbook (Sprint 5)

Production topology: **Vercel** (Next.js frontend) + **AWS** (containerised FastAPI
API and Celery worker) + managed **Postgres (pgvector)** + **Redis** + **S3**.

```
[Vercel: Next.js] ──HTTPS──> [AWS: FastAPI API] ──> Postgres (pgvector)
                                    │  └─> Redis (broker + cache + telemetry)
                                    └─> S3 (RFP uploads)
                             [AWS: Celery worker] ──> parse → Gemini → Postgres
```

The deploy workflow builds and pushes the backend image to **ECR**; you run it on
your chosen orchestrator (ECS / EKS / EC2) with two commands from the same image.

---

## 1. Prerequisites

- Postgres 15+ with the `vector` extension (e.g. RDS + pgvector, or `ankane/pgvector`).
- Redis 7 (e.g. ElastiCache).
- An S3 bucket for uploads (set `USE_LOCALSTACK=false` + AWS creds/role in prod).
- A Google **Gemini API key**.
- ECR repository for the backend image.
- Vercel project for the frontend.

## 2. Configuration

Copy the templates and fill them in — never commit real secrets (`.env` is
gitignored):

- **Root (Docker Compose):** `.env.example` → `.env` — DB credentials/ports plus
  all backend vars. Compose auto-loads this file for `${VAR}` substitution.
- Backend (host runs, non-Docker): `backend/.env.example` → `backend/.env`
- Frontend: `proposalai-frontend/.env.example` → `.env.local`

Generate a strong `JWT_SECRET` (e.g. `openssl rand -hex 32`).

### The refresh cookie, and the one setting that will catch you

The refresh token is an **HttpOnly cookie**, not a value in the login response,
so no script on the page can read it. The access token is short-lived (15
minutes) and held only in the browser's memory.

That works out of the box in development because `localhost:3000` and
`localhost:8000` are *same-site* — different ports do not make a different site.
In production the Vercel app and the API are different registrable domains,
which is **cross-site**, and there the browser silently refuses to store the
cookie unless it is `SameSite=None`, and silently ignores `SameSite=None`
unless `Secure` is also set. So in production:

```bash
COOKIE_SAMESITE=none
COOKIE_SECURE=true      # requires HTTPS on the API, which you want anyway
CORS_ORIGINS=https://your-app.vercel.app   # never "*" — credentials require an exact origin
```

The failure mode if you skip this is specific and misleading: **sign-in
succeeds**, the app works until the first access token expires, and then every
request 401s and the user is bounced to the login page in a loop. Nothing logs
an error, because from the server's point of view the client simply never sent
a cookie.

If the API and the app share a parent domain (`app.example.com` /
`api.example.com`), you can instead set `COOKIE_DOMAIN=.example.com` and keep
`SameSite=Lax`, which is the stronger configuration — prefer it when the DNS
allows.

## 3. Database migration

The schema is managed by **Alembic** (`backend/migrations/`). One command, the
same one CI and the deploy workflow run:

```bash
cd backend
alembic upgrade head
```

`DATABASE_URL` is the only input — `migrations/env.py` reads it through the
app's own settings object, so a migration can only ever target the database the
app itself would talk to. There is no URL in `alembic.ini` to get out of sync.

**An existing database** (a pre-Alembic environment, or a dev container whose
`init_scripts` already ran) is adopted once, without applying anything:

```bash
alembic stamp 0001_baseline
alembic current                # → 0001_baseline (head)
```

**Useful checks:**

```bash
alembic current                # what this database believes it is at
alembic history --verbose      # the full revision chain
alembic upgrade head --sql     # render SQL instead of executing (hand to a DBA)
alembic downgrade -1           # step back one revision
```

### Expand-then-contract

The deploy workflow applies migrations in a dedicated `migrate` job, gated on
the `production` environment and ordered after the image build. Because the
migration lands while the previous image is still serving, schema changes must
be **expand-then-contract**: add the new column in one release, stop reading the
old one in the next, drop it in a third.

**This applies from the first production deploy onward, and not before it.**
Until an environment is actually serving traffic there is no old image to stay
compatible with, so an expand and its contract may ship together. Two pairs have
already done so, deliberately:

| Expand | Contract | Shipped together because |
|--------|----------|--------------------------|
| `0002` (`proposal_sections.proposal_id`) | `0003` (drop `rfp_id`) | Production was not provisioned; no deployed image had ever read this schema. |
| `0005` (`proposals.drafting_status`) | `0006` (drop drafting states from `rfp_documents`) | Same. |

Once §5 is done and a production database exists, that reasoning expires: split
every subsequent pair across releases, and say so in the revision docstring so
the next person does not have to reconstruct the decision from the dates.

`backend/init_scripts/*.sql` is frozen historical record — see the README there.
Do not add files to it.

## 4. Local development

```bash
cp .env.example .env            # then set GEMINI_API_KEY (and a strong JWT_SECRET)
```

**Full stack** (`docker-compose.yml`) — db, redis, localstack, backend (:8000),
celery-worker, all reading the root `.env`:

```bash
docker compose up --build
cd proposalai-frontend && npm run dev   # :3000
```

**Databases only** (`docker-compose.db.yml`) — run just Postgres/Redis/LocalStack
in containers while developing the backend on the host:

```bash
docker compose -f docker-compose.db.yml up -d
cd backend && uvicorn app.main:app --reload   # uses backend/.env
```

The Postgres named volume persists across runs; the `init_scripts` only run on a
fresh volume. After changing DB credentials in `.env`, reset with
`docker compose down -v` before `up`.

## 5. CI (`.github/workflows/ci.yml`)

Runs on every push/PR: backend `pytest` (against ephemeral Postgres+Redis
services with the schema applied) and frontend `tsc --noEmit` + `next build`.

## 6. Backend deploy → ECR (`.github/workflows/deploy.yml`)

Triggered by a `v*` tag or manual dispatch. Builds `backend/Dockerfile.prod`
(gunicorn + uvicorn workers) and pushes `:$TAG` and `:latest` to ECR.

**Required GitHub secrets:** `AWS_DEPLOY_ROLE_ARN` (OIDC role), `AWS_REGION`,
`ECR_REPOSITORY`.

Run the pushed image on your orchestrator with the correct command per role:

```bash
# API
gunicorn app.main:app -k uvicorn.workers.UvicornWorker -w 4 -b 0.0.0.0:8000
# Worker (same image, override command)
celery -A app.worker.celery_app:celery_app worker --loglevel=info --concurrency=2
```

Both need the backend env vars from step 2.

## 7. Frontend deploy → Vercel

The deploy workflow's `frontend-vercel` job runs `vercel build/deploy --prod`.

**Required GitHub secrets:** `VERCEL_TOKEN`, `VERCEL_ORG_ID`, `VERCEL_PROJECT_ID`.
Set `NEXT_PUBLIC_API_URL` (and optional Sentry/PostHog keys) in Vercel's project
env settings.

## 8. Observability

- `GET /health` — liveness (process up).
- `GET /ready` — readiness; 200 only when Postgres **and** Redis are reachable.
  Wire load-balancer / ECS health checks here.
- `GET /metrics` — per-model LLM call counts, token usage, avg latency, and
  estimated cost (aggregated across API + worker via Redis). Restrict at the
  network layer in production.
- **Sentry** — set `SENTRY_DSN` (backend) and `NEXT_PUBLIC_SENTRY_DSN` (frontend).
- **PostHog** — set `NEXT_PUBLIC_POSTHOG_KEY` / `NEXT_PUBLIC_POSTHOG_HOST`.

All telemetry is fail-open and disabled by default without keys.

## 9. Closed alpha checklist (Story 5.5)

- [ ] `alembic current` reports `head` against the target database; `GET /ready` returns 200.
- [ ] `JWT_SECRET`, `GEMINI_API_KEY`, S3, Redis, DB secrets set (not defaults).
- [ ] `COOKIE_SECURE=true` + `COOKIE_SAMESITE=none` (cross-site) or `COOKIE_DOMAIN` (shared parent) — see §2.
- [ ] `USE_LOCALSTACK=false` with a real bucket + least-privilege IAM.
- [ ] `CORS_ORIGINS` set to the Vercel domain (defaults to `localhost:3000`).
- [ ] Sentry + PostHog keys configured; a test error appears in Sentry.
- [ ] Upload → parse → extract → requirements visible end to end.
- [ ] `/metrics` shows token spend after a generation.
- [ ] First alpha users created via `POST /auth/register`; daily bug triage set up.

## 10. Known follow-ups

- `DATABASE_URL` must be set as a repository/environment secret for the deploy
  workflow's `migrate` job, or the deploy fails at that step by design.
- `/metrics` is unauthenticated — keep it off the public internet (network ACL).
