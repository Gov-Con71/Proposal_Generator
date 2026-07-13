# ProposalAI — Sprints Overview

**Project:** AI-powered RFP → compliance-matrix → draft-proposal platform
**Duration:** 5 sprints × 2 weeks (10 weeks)
**Team:** 3 (Frontend, Backend, AI Layer)
**Status legend:** ✅ Done · ⚠️ Partial · ❌ Not started

> Work is currently split across unmerged branches. The full frontend UI lives on
> `origin/main`; the backend + AI ingestion pipeline lives on `Document_Ingestion_Pipeline`.
> No single branch is yet a working end-to-end system, and the frontend runs entirely on
> mock data (the backend↔frontend API contract is not wired).

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

| Sprint | Theme | Overall |
|--------|-------|---------|
| 1 | Foundation & Data Contracts | ⚠️ ~70% — scaffolding in place, API contract & workspaces/pgvector missing |
| 2 | Document Ingestion Pipeline | ⚠️ ~60% — parser & extractor work in isolation; no upload API, no persistence |
| 3 | RAG Engine & Workspace | ❌ ~15% — workspace UI built (mock); RAG entirely unstarted |
| 4 | Interactive Grid & Guardrails | ⚠️ ~20% — grid UI built (mock); security/tuning/guardrails missing |
| 5 | Deployment & Alpha | ❌ ~5% — nothing beyond an AI PR-review action |

## Critical-path gaps (blocking end-to-end)

1. **`POST /documents/upload` API route** — S3 streaming exists as a script, not an endpoint (2.2).
2. **Real worker → DB ingestion** — replace the stdout mock with inserts into `extracted_requirements` (2.5).
3. **CRUD endpoints** for requirements & proposal sections — frontend already calls them (3.4).
4. **Auth + multi-tenant isolation** — currently a mock cookie; no backend auth (1.4, 4.2).
5. **The entire RAG layer** — pgvector schema, embedding pipeline, vector search, draft writer (Sprint 3).
6. **Branch integration** — consolidate backend + `main` frontend onto one branch and wire the API contract.
