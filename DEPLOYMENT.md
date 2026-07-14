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

## 3. Database migration

The schema is plain SQL applied in order (no migration framework yet). Locally,
Docker runs these automatically via `docker-entrypoint-initdb.d`. In production
apply them once against the target database:

```bash
psql "$DATABASE_URL" -f backend/init_scripts/init_schema.sql
psql "$DATABASE_URL" -f backend/init_scripts/rag_schema.sql   # pgvector + history + section.status
psql "$DATABASE_URL" -f backend/init_scripts/tuning.sql       # indexes + ANALYZE
```

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

- [ ] Schema applied; `GET /ready` returns 200 in the target environment.
- [ ] `JWT_SECRET`, `GEMINI_API_KEY`, S3, Redis, DB secrets set (not defaults).
- [ ] `USE_LOCALSTACK=false` with a real bucket + least-privilege IAM.
- [ ] `CORS_ORIGINS` set to the Vercel domain (defaults to `localhost:3000`).
- [ ] Sentry + PostHog keys configured; a test error appears in Sentry.
- [ ] Upload → parse → extract → requirements visible end to end.
- [ ] `/metrics` shows token spend after a generation.
- [ ] First alpha users created via `POST /auth/register`; daily bug triage set up.

## 10. Known follow-ups

- No migration framework yet (raw SQL applied in order). Consider Alembic as the
  schema grows.
- `/metrics` is unauthenticated — keep it off the public internet (network ACL).
