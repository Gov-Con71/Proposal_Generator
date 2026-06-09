// ─── proposals.ts ────────────────────────────────────────────────────────────
import apiClient from './client'
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
export const documentsApi = {
  upload: (file: File, proposalId: string, onProgress?: (pct: number) => void) => {
    const form = new FormData()
    form.append('file', file)
    form.append('proposal_id', proposalId)
    return apiClient.post('/documents/upload', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
      onUploadProgress: (e) => {
        if (onProgress && e.total) onProgress(Math.round((e.loaded / e.total) * 100))
      },
    }).then((r) => r.data)
  },

  reanalyze: (documentId: string) =>
    apiClient.post(`/documents/${documentId}/reanalyze`).then((r) => r.data),
}

// ─── requirements.ts ──────────────────────────────────────────────────────────
import type { Requirement } from '@/types'

export const requirementsApi = {
  list: (proposalId: string) =>
    apiClient.get<Requirement[]>(`/proposals/${proposalId}/requirements`).then((r) => r.data),

  update: (id: string, data: Partial<Requirement>) =>
    apiClient.patch<Requirement>(`/requirements/${id}`, data).then((r) => r.data),
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
}

// ─── compliance.ts ────────────────────────────────────────────────────────────
export const complianceApi = {
  matrix: (proposalId: string) =>
    apiClient.get(`/proposals/${proposalId}/compliance`).then((r) => r.data),
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