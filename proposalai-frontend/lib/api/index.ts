// ─── auth.ts ─────────────────────────────────────────────────────────────────
import apiClient from './client'
import type { Session, User } from '@/types'

export interface RegisterPayload {
  email: string
  password: string
  firstName: string
  lastName: string
  /** Organisation name. Signing up under an existing name joins that company. */
  company?: string
}

export const authApi = {
  login: (email: string, password: string) =>
    apiClient.post<Session>('/auth/login', { email, password }).then((r) => r.data),

  register: (data: RegisterPayload) =>
    apiClient.post<Session>('/auth/register', data).then((r) => r.data),

  me: () => apiClient.get<User>('/auth/me').then((r) => r.data),

  // No token argument on refresh or logout: the refresh token is an HttpOnly
  // cookie the browser attaches and this code cannot read. That is the point —
  // see lib/stores/auth-store.ts. Session bootstrap goes through
  // `bootstrapSession` in ./client, which shares one in-flight refresh.
  refresh: () =>
    apiClient.post<Session>('/auth/refresh').then((r) => r.data),

  // The server revokes the cookie's token and clears the cookie; without this
  // call, signing out would only drop client state and leave the session
  // rotatable by anyone who still held the token.
  logout: () => apiClient.post('/auth/logout').then((r) => r.data),

  /** Change the password, which signs every session out — including this one. */
  changePassword: (currentPassword: string, newPassword: string) =>
    apiClient
      .post<{ message: string }>('/auth/password', { currentPassword, newPassword })
      .then((r) => r.data),
}

// ─── proposals.ts ────────────────────────────────────────────────────────────
import type { Proposal, ProposalSummary } from '@/types'

export const proposalsApi = {
  list: () =>
    apiClient.get<ProposalSummary[]>('/proposals').then((r) => r.data),

  get: (id: string) =>
    apiClient.get<Proposal>(`/proposals/${id}`).then((r) => r.data),

  create: (data: Partial<Proposal>) =>
    apiClient.post<Proposal>('/proposals', data).then((r) => r.data),

  update: (id: string, data: Partial<Proposal>) =>
    apiClient.patch<Proposal>(`/proposals/${id}`, data).then((r) => r.data),

  delete: (id: string) =>
    apiClient.delete(`/proposals/${id}`).then((r) => r.data),
}

// ─── documents.ts ─────────────────────────────────────────────────────────────
import type { SolicitationSummary } from '@/types'

export interface UploadResult {
  /** The proposal created for this upload — the id every /proposals/… route
   *  is keyed on, and what the client navigates by. */
  proposalId: string
  /** The ingested RFP behind it. Only needed for /documents/{rfpId} status. */
  rfpId: string
  fileName: string
  sizeBytes: number
  s3Key: string
  processingStatus: string
}

export interface DocumentStatus {
  rfpId: string
  fileName: string
  processingStatus: string
  requirementsCount: number
  /** Why ingestion or drafting failed, when processingStatus is 'failed' or
   *  'draft_failed'. Null otherwise. Lets the UI distinguish a provider/config
   *  problem from an unreadable document instead of just saying "failed". */
  failureReason?: string | null
}

/** Bid metadata the upload form collects, applied to the proposal the upload
 *  creates. Keys are the snake_case multipart field names the endpoint expects
 *  (multipart fields are not camel-converted the way JSON bodies are). */
export interface UploadMeta {
  title?: string
  agency?: string
  solicitation_number?: string
  due_date?: string
  contract_type?: string
  naics_code?: string
}

/** Response from POST /proposals/{proposalId}/pipeline/ticket. */
export interface StreamTicket {
  ticket: string
  expiresInSeconds: number
}

/** Response from POST /proposals/{proposalId}/draft. */
export interface DraftQueued {
  proposalId: string
  rfpId: string
  /** The proposal's own drafting lifecycle — always 'drafting' here. */
  draftingStatus: string
  requirementsCount: number
}

export const documentsApi = {
  // Streams the file to POST /documents/upload. The tenant is derived from the
  // JWT the axios client attaches — no user id in the body.
  upload: (file: File, onProgress?: (pct: number) => void, meta?: UploadMeta) => {
    const form = new FormData()
    form.append('file', file)
    // Bid metadata from the upload form. Sent as multipart fields beside the
    // file; the server applies whatever is filled in to the proposal it creates
    // and leaves the rest to ingestion. Empty values are omitted rather than
    // sent as '' so they cannot overwrite anything extraction later derives.
    if (meta) {
      for (const [key, value] of Object.entries(meta)) {
        if (value) form.append(key, value)
      }
    }
    return apiClient.post<UploadResult>('/documents/upload', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
      onUploadProgress: (e) => {
        if (onProgress && e.total) onProgress(Math.round((e.loaded / e.total) * 100))
      },
    }).then((r) => r.data)
  },

  // Poll ingestion status (pending → parsing → extracting → completed/failed).
  status: (rfpId: string) =>
    apiClient.get<DocumentStatus>(`/documents/${rfpId}`).then((r) => r.data),

  // Kick off the full drafting agent (POST /proposals/{proposalId}/draft).
  // Addressed by proposal, not document: drafting writes that proposal's own
  // sections, and one RFP can back several proposals. Queues the worker and
  // returns draftingStatus 'drafting'; poll proposalsApi.get(proposalId) until
  // its draftingStatus becomes 'drafted' (or 'draft_failed'). Polling the
  // *document* would report whichever bid on that RFP wrote last — the flag
  // moved onto the proposal in migration 0005.
  // 409 if the RFP has no requirements yet.
  draft: (proposalId: string) =>
    apiClient.post<DraftQueued>(`/proposals/${proposalId}/draft`).then((r) => r.data),

  // Mint a single-use ticket for the SSE progress stream. EventSource cannot
  // send an Authorization header, so this authenticated POST is exchanged for a
  // credential narrow enough to survive being in a URL: one proposal, one use,
  // a few seconds. It replaces passing the access token as ?token=.
  streamTicket: (proposalId: string) =>
    apiClient
      .post<StreamTicket>(`/proposals/${proposalId}/pipeline/ticket`)
      .then((r) => r.data),

  // Read the extracted solicitation summary (GET /documents/{rfpId}/summary).
  // Supplementary/best-effort: the server returns 404 until it exists, so a
  // polling caller should treat a 404 as "not ready yet" rather than an error.
  // The payload is verbatim snake_case (see SolicitationSummary).
  getSummary: (rfpId: string) =>
    apiClient.get<SolicitationSummary>(`/documents/${rfpId}/summary`).then((r) => r.data),

  reanalyze: (documentId: string) =>
    apiClient.post<DocumentStatus>(`/documents/${documentId}/reanalyze`).then((r) => r.data),
}

// ─── requirements.ts ──────────────────────────────────────────────────────────
import type { Requirement } from '@/types'

export const requirementsApi = {
  list: (proposalId: string) =>
    apiClient.get<Requirement[]>(`/proposals/${proposalId}/requirements`).then((r) => r.data),

  update: (id: string, data: Partial<Requirement>) =>
    apiClient.patch<Requirement>(`/requirements/${id}`, data).then((r) => r.data),

  delete: (id: string) =>
    apiClient.delete(`/requirements/${id}`).then((r) => r.data),
}

// ─── sections.ts ──────────────────────────────────────────────────────────────
import type { ProposalSection } from '@/types/index'

export const sectionsApi = {
  list: (proposalId: string) =>
    apiClient.get<ProposalSection[]>(`/proposals/${proposalId}/sections`).then((r) => r.data),

  get: (id: string) =>
    apiClient.get<ProposalSection>(`/sections/${id}`).then((r) => r.data),

  update: (id: string, content: string) =>
    apiClient.patch<ProposalSection>(`/sections/${id}`, { content }).then((r) => r.data),

  approve: (id: string) =>
    apiClient.post<ProposalSection>(`/sections/${id}/approve`).then((r) => r.data),

  regenerate: (id: string) =>
    apiClient.post<ProposalSection>(`/sections/${id}/regenerate`).then((r) => r.data),

  // Create a section for a requirement and fill it with a RAG-generated draft.
  generate: (proposalId: string, requirementId: string) =>
    apiClient
      .post<ProposalSection>(`/proposals/${proposalId}/sections/generate`, { requirementId })
      .then((r) => r.data),
}

// ─── history.ts (RAG past-performance) ────────────────────────────────────────
export interface HistorySource {
  sourceName: string
  chunks: number
  createdAt: string
}

export interface HistoryIngestResult {
  sourceName: string
  chunks: number
}

// Past-performance evidence lives in two pools. Omitting `proposalId` targets
// the long-term library, reusable across every bid; passing one targets that
// proposal's own supporting documents, which are deleted with the proposal.
// Every call takes the same optional argument so the two pages share this API.
export const historyApi = {
  list: (proposalId?: string) =>
    apiClient
      .get<HistorySource[]>('/history', { params: proposalId ? { proposalId } : undefined })
      .then((r) => r.data),

  ingest: (sourceName: string, content: string, proposalId?: string) =>
    apiClient
      .post<HistoryIngestResult>('/history', { sourceName, content }, {
        params: proposalId ? { proposalId } : undefined,
      })
      .then((r) => r.data),

  upload: (file: File, proposalId?: string) => {
    const form = new FormData()
    form.append('file', file)
    // Sent as a form field rather than a query param: the endpoint reads it
    // with Form(), keeping the whole request in one multipart body.
    if (proposalId) form.append('proposalId', proposalId)
    return apiClient
      .post<HistoryIngestResult>('/history/upload', form, {
        headers: { 'Content-Type': 'multipart/form-data' },
        // Parsing plus a single embedding round-trip; well past the 30s default.
        timeout: 180_000,
      })
      .then((r) => r.data)
  },

  remove: (sourceName: string, proposalId?: string) =>
    apiClient
      .delete(`/history/${encodeURIComponent(sourceName)}`, {
        params: proposalId ? { proposalId } : undefined,
      })
      .then((r) => r.data),
}

// ─── compliance.ts ────────────────────────────────────────────────────────────
export const complianceApi = {
  matrix: (proposalId: string) =>
    apiClient.get(`/proposals/${proposalId}/compliance`).then((r) => r.data),
}

// ─── integrity.ts ─────────────────────────────────────────────────────────────
import type { IntegrityItem } from '@/types'

export const integrityApi = {
  // Pre-export checklist derived server-side from the compliance matrix + sections.
  list: (proposalId: string) =>
    apiClient.get<IntegrityItem[]>(`/proposals/${proposalId}/integrity`).then((r) => r.data),
}

// ─── profile.ts ───────────────────────────────────────────────────────────────
import type { CompanyProfile } from '@/types/index'

export const profileApi = {
  get: () =>
    apiClient.get<CompanyProfile>('/profile').then((r) => r.data),

  save: (data: Partial<CompanyProfile>) =>
    apiClient.put<CompanyProfile>('/profile', data).then((r) => r.data),
}

// ─── export.ts ────────────────────────────────────────────────────────────────
import type { ExportFormat, ExportJob } from '@/types'

export const exportApi = {
  create: (proposalId: string, format: ExportFormat) =>
    apiClient.post<ExportJob>('/exports', { proposalId, format }).then((r) => r.data),

  get: (jobId: string) =>
    apiClient.get<ExportJob>(`/exports/${jobId}`).then((r) => r.data),

  download: (downloadUrl: string) =>
    apiClient.get(downloadUrl, { responseType: 'blob' }).then((r) => r.data),
}