# Proposal_Generator

AI system to aid in proposal generation.

AI-assisted RFP proposal drafting: ingest an RFP → extract requirements/compliance
matrix → retrieve relevant past-performance content (RAG) → draft each section
with an LLM, grounded and citation-tagged.

**Stack:** FastAPI backend + Celery worker (`backend/`) + Next.js frontend
(`proposalai-frontend/`) + Postgres/pgvector + Redis + LocalStack (S3 stand-in).
Runs locally under **rootless Podman** via `podman compose` (a Docker Compose
CLI plugin talking to Podman's Docker-compatible API — not `podman-compose`).
Docker works the same way if that's what you have installed; just swap
`podman compose` for `docker compose` below.

See `GAP_ANALYSIS.md` / `SPRINTS_OVERVIEW.md` for project history.

## Setup

```bash
cp .env.example .env
```

Then edit `.env` and set a real `GEMINI_API_KEY` (or switch `LLM_PROVIDER` to
`featherless` and set `FEATHERLESS_API_KEY` — see the comments in
`.env.example` for the flat-rate alternative to Gemini's free-tier daily cap).

## Running everything in containers (simplest)

```bash
podman compose -f docker-compose.app.yml up --build -d
```

Brings up backend, celery-worker, frontend, Postgres/pgvector, Redis, and
LocalStack together.

- Frontend: http://localhost:3000
- Backend API: http://localhost:8000 (see `GET /health`, `/ready`, `/metrics`
  in `backend/app/api/v1/monitoring.py`)

Stop it with:

```bash
podman compose -f docker-compose.app.yml down
```

## Running backend/frontend on the host, infra in containers

Useful for active development (hot reload, debugger attached, etc.).

```bash
podman compose -f docker-compose.db.yml up -d
```

Starts only Postgres/pgvector, Redis, and LocalStack.

### Backend (host)

```bash
cd backend
python -m venv venv && source venv/bin/activate   # first time only
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Make sure `.env` points `DATABASE_URL`, `CELERY_BROKER_URL`,
`CELERY_RESULT_BACKEND`, `CACHE_URL`, and `LOCALSTACK_ENDPOINT` at `localhost`
(the `.env.example` defaults already do this) rather than the in-compose
service names.

### Celery worker (host)

```bash
cd backend
source venv/bin/activate
celery -A app.core.celery_app worker --loglevel=info
```

### Frontend (host)

```bash
cd proposalai-frontend
npm install
npm run dev
```

Frontend runs at http://localhost:3000, backend at http://localhost:8000.

## Backend + celery-worker in containers, no frontend container

```bash
podman compose -f docker-compose.yml up --build -d
```

Then run the frontend on the host as above.

## Tests

Backend (against the live compose stack's Postgres/Redis):

```bash
podman exec fastapi_backend_app python -m pytest tests/ -q
```

Frontend:

```bash
cd proposalai-frontend
npm run test        # unit tests (vitest)
npm run test:e2e    # Playwright e2e
npm run lint
npm run type-check
```
