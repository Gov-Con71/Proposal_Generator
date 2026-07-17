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

  // Rotating refresh tokens: the server consumes the old one and returns a new
  // session. Replaying a consumed token revokes every session for that user.
  refresh: (refreshToken: string) =>
    apiClient.post<Session>('/auth/refresh', { refreshToken }).then((r) => r.data),

  // Sending the refresh token lets the server actually revoke it; without it,
  // logout would only clear client state and leave the session rotatable.
  logout: (refreshToken?: string) =>
    apiClient.post('/auth/logout', refreshToken ? { refreshToken } : {}).then((r) => r.data),
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
}

export const documentsApi = {
  // Streams the file to POST /documents/upload. The tenant is derived from the
  // JWT the axios client attaches — no user id in the body.
  upload: (file: File, onProgress?: (pct: number) => void) => {
    const form = new FormData()
    form.append('file', file)
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

export const historyApi = {
  list: () => apiClient.get<HistorySource[]>('/history').then((r) => r.data),

  ingest: (sourceName: string, content: string) =>
    apiClient
      .post<{ sourceName: string; chunks: number }>('/history', { sourceName, content })
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