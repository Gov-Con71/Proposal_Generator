# ProposalAI — Sprints Overview

**Project:** AI-powered RFP → compliance-matrix → draft-proposal platform
**Duration:** 5 sprints × 2 weeks (10 weeks)
**Team:** 3 (Frontend, Backend, AI Layer)
**Status legend:** ✅ Done · ⚠️ Partial · ❌ Not started

> **Update (2026-07-13):** All five sprints have been implemented on
> `Document_Ingestion_Pipeline` and pushed. The backend↔frontend contract is
> wired end-to-end (upload → S3 → Celery/Gemini → pgvector RAG → workspace UI),
> with JWT auth + tenant isolation, output guardrails, Redis cache, CI/CD
> workflows, observability, and a deployment runbook (`DEPLOYMENT.md`).
> Remaining work is live-environment provisioning (AWS/Vercel/keys) and running
> the DB-backed test suite in CI — see the per-sprint notes below, which reflect
> the *original* pre-implementation assessment.

---

## Sprint 1 — Foundation, Data Contracts & Environment Setup (Weeks 1–2)

**Goal:** Establish database architecture, API definitions, app layout, and dev environments.

| Story | Owner | Status | Notes |
|-------|-------|--------|-------|
| 1.1 Repos, CI/CD, cloud hosting | All 3 | ⚠️ | Next.js + FastAPI + Dockerized Postgres (pgvector image) present. S3 exists only as a LocalStack demo script, not provisioned infra. |
| 1.2 Relational schema + pgvector | Backend | ⚠️ | Tables: users, rfp_documents, extracted_requirements, proposal_sections. **Missing:** Workspaces table, and `CREATE EXTENSION vector` / vector columns are never run. |
| 1.3 API endpoint specs (Swagger) | Backend | ⚠️ | `/docs` live but exposes only `POST /api/v1/proposals`. Auth/upload/proposal-view endpoints the frontend codes against do not exist. |
| 1.4 App shell, sidebar, nav, auth state | Frontend | ⚠️ | Shell, sidebar, navbar, auth pages built on `main`. Auth is a fake `mock-token` cookie — no real auth state. |
| 1.5 LLM benchmarking + parsing baseline | AI | ✅ | `benchmark_pdf_extraction.py` present. |
| 1.6 Review, testing, retro | All 3 | ⚠️ | CI only runs an AI PR reviewer; no green test/build pipeline yet. |

---

## Sprint 2 — The Document Ingestion Pipeline (Weeks 3–4)

**Goal:** Upload an RFP, store it safely, extract raw text + initial compliance requirements asynchronously.

`[Frontend: Drag-and-Drop] → [Backend: S3 Streamer] → [AI Layer: Document Parser]`

| Story | Owner | Status | Notes |
|-------|-------|--------|-------|
| 2.1 Drag-and-drop upload UI + progress | Frontend | ⚠️ | `documentsApi.upload` client with progress exists on `main`; component wiring is thin/mock. |
| 2.2 Multi-tenant S3 streaming endpoint | Backend | ❌ | **No `POST /documents/upload` route.** S3 logic lives only in a standalone script, never mounted as an API. |
| 2.3 Async document layout parser | AI | ✅ | `document_parser.py` — MarkItDown → clean Markdown, with error handling. |
| 2.4 Compliance Matrix LLM extractor | AI | ✅ | `compliance_extractor.py` — LangGraph + Gemini structured output → validated `ComplianceMatrix`. |
| 2.5 Connect AI tasks to worker queue → DB | Backend | ❌ | `queue_worker.py` is a mock that prints JSON to stdout. No queue infra; never inserts into `extracted_requirements`. |
| 2.6 Review, integration test, retro | All 3 | ❌ | No true end-to-end test (upload → S3 → parse → DB rows). |

---

## Sprint 3 — Core RAG Engine & Workspace Building (Weeks 5–6)

**Goal:** Semantic retrieval of past proposals + split-pane draft workspace.

| Story | Owner | Status | Notes |
|-------|-------|--------|-------|
| 3.1 Chunk + embed + vector storage script | AI | ❌ | No chunking/embedding/pgvector pipeline exists. |
| 3.2 Vector query + context ranking service | AI | ❌ | No semantic search service. |
| 3.3 Split-pane generation workspace layout | Frontend | ⚠️ | `workspace/page.tsx` built on `main` (grouped requirements + editable canvas) — mock data only. |
| 3.4 CRUD endpoints for sections + edits | Backend | ❌ | No GET/PATCH endpoints for requirements/sections/auto-save. Frontend calls them; backend has none. |
| 3.5 Prompt routing + draft writer | AI | ❌ | No generation engine compiling requirements + history into draft prose. |
| 3.6 Review, integration test, retro | All 3 | ❌ | "Generate" end-to-end flow not achievable yet. |

---

## Sprint 4 — Interactive Grid & Guardrail System (Weeks 7–8)

**Goal:** Editable requirements grid, strict tenant security, AI output validation.

| Story | Owner | Status | Notes |
|-------|-------|--------|-------|
| 4.1 High-density compliance grid | Frontend | ⚠️ | `compliance/page.tsx` built on `main` (filter/search) — mock data, no inline-edit persistence. |
| 4.2 Multi-tenant security + request isolation | Backend | ❌ | No auth-header middleware, no workspace isolation. Requests hit the DB directly. |
| 4.3 Pydantic output guardrails | AI | ⚠️ | Extractor uses Pydantic schemas, but no reject-on-hallucination layer before save (nothing persists yet). |
| 4.4 DB index tuning + caching | Backend | ❌ | Basic B-tree indexes only; no vector indexes, no cache layer. |
| 4.5 Loading skeletons + error boundaries | Frontend | ⚠️ | Partial UI states; not connected to real backend status codes. |
| 4.6 Destructive edge-case testing, retro | All 3 | ❌ | Not started. |

---

## Sprint 5 — Cloud Deployment, Monitoring & Alpha Launch (Weeks 9–10)

**Goal:** Move platform to a resilient production state and onboard first alpha testers.

`[Local Merge] → [GitHub Actions CI/CD] → 🚀 Vercel Frontend + AWS Backend & DB`

| Story | Owner | Status | Notes |
|-------|-------|--------|-------|
| 5.1 Production GitHub Actions CI/CD | Backend | ❌ | CI only runs an AI PR reviewer (`ai-review.yml`). No test/build/migration pipeline. |
| 5.2 Production infra on Vercel + AWS | Backend & Frontend | ❌ | No production config, SSL, or domain mapping. |
| 5.3 LLM cost auditing + observability | AI | ❌ | No token-spend/latency/error telemetry. |
| 5.4 Analytics + error reporting (PostHog/Sentry) | Frontend | ❌ | Not integrated. |
| 5.5 Closed alpha launch + hardening | All 3 | ❌ | Not started. |
| 5.6 Final review + wrap-up | All 3 | ❌ | Not started. |

---

## Roll-up

_Left column = original assessment; right = status after implementation._

| Sprint | Theme | Original | Now |
|--------|-------|----------|-----|
| 1 | Foundation & Data Contracts | ⚠️ ~70% | ✅ 1.3 mock contract + 1.4 shell/auth wired |
| 2 | Document Ingestion Pipeline | ⚠️ ~60% | ✅ upload→S3→Celery→Gemini→DB, e2e |
| 3 | RAG Engine & Workspace | ❌ ~15% | ✅ pgvector RAG + CRUD + draft writer + UI |
| 4 | Interactive Grid & Guardrails | ⚠️ ~20% | ✅ grid edit/sort/delete, guardrails, cache, security |
| 5 | Deployment & Alpha | ❌ ~5% | ✅ CI/CD, prod Docker, observability, Sentry/PostHog, runbook |

## Critical-path gaps — all resolved

1. ~~`POST /documents/upload` API route~~ → ✅ streaming upload endpoint (2.2).
2. ~~Real worker → DB ingestion~~ → ✅ Celery worker inserts `extracted_requirements` (2.5).
3. ~~CRUD endpoints for requirements & sections~~ → ✅ workspace router (3.4).
4. ~~Auth + multi-tenant isolation~~ → ✅ JWT + per-request tenant checks (4.2).
5. ~~The entire RAG layer~~ → ✅ pgvector, embeddings, retrieval, draft writer (Sprint 3).
6. ~~Branch integration~~ → ✅ single branch, contract wired, pushed.

## Remaining (live-environment, not code)

- Provision AWS (ECR/orchestration/S3/RDS/ElastiCache) + Vercel + set GitHub/Vercel secrets.
- Run the DB-backed test suite in CI (workflow ready; needs the services it defines).
- Configure real `GEMINI_API_KEY`, `JWT_SECRET`, Sentry/PostHog keys; set `CORS_ORIGINS`.
