// ─── use-proposals.ts ─────────────────────────────────────────────────────────
import { useQuery } from '@tanstack/react-query'
import { proposalsApi } from '@/lib/api'
import { MOCK_PROPOSALS } from '@/lib/constants/mock-data'

export function useProposals() {
  return useQuery({
    queryKey: ['proposals'],
    queryFn: proposalsApi.list,
    placeholderData: MOCK_PROPOSALS,
  })
}

// ─── use-proposal.ts ──────────────────────────────────────────────────────────
import { MOCK_PROPOSAL } from '@/lib/constants/mock-data'

export function useProposal(id: string) {
  return useQuery({
    queryKey: ['proposals', id],
    queryFn: () => proposalsApi.get(id),
    placeholderData: MOCK_PROPOSAL,
    enabled: !!id,
  })
}

// ─── use-requirements.ts ──────────────────────────────────────────────────────
import { requirementsApi } from '@/lib/api'
import { MOCK_REQUIREMENTS } from '@/lib/constants/mock-data'

export function useRequirements(proposalId: string) {
  return useQuery({
    queryKey: ['requirements', proposalId],
    queryFn: () => requirementsApi.list(proposalId),
    placeholderData: MOCK_REQUIREMENTS,
    enabled: !!proposalId,
  })
}

// ─── use-sections.ts ──────────────────────────────────────────────────────────
import { sectionsApi } from '@/lib/api'
import { MOCK_SECTIONS } from '@/lib/constants/mock-data'

export function useSections(proposalId: string) {
  return useQuery({
    queryKey: ['sections', proposalId],
    queryFn: () => sectionsApi.list(proposalId),
    placeholderData: MOCK_SECTIONS,
    enabled: !!proposalId,
  })
}

// ─── use-integrity.ts ─────────────────────────────────────────────────────────
import { integrityApi } from '@/lib/api'
import { MOCK_INTEGRITY_ITEMS } from '@/lib/constants/mock-data'

export function useIntegrity(proposalId: string) {
  return useQuery({
    queryKey: ['integrity', proposalId],
    queryFn: () => integrityApi.list(proposalId),
    placeholderData: MOCK_INTEGRITY_ITEMS,
    enabled: !!proposalId,
  })
}

// ─── use-compliance.ts ────────────────────────────────────────────────────────
import { useState } from 'react'
import type { ComplianceStatus } from '@/types'

export function useCompliance(proposalId: string) {
  const [filter, setFilter] = useState<ComplianceStatus | 'all'>('all')
  const { data: requirements = [], ...rest } = useRequirements(proposalId)

  const filtered = filter === 'all'
    ? requirements
    : requirements.filter((r) => r.complianceStatus === filter)

  const counts = {
    all:       requirements.length,
    addressed: requirements.filter((r) => r.complianceStatus === 'addressed').length,
    partial:   requirements.filter((r) => r.complianceStatus === 'partial').length,
    missing:   requirements.filter((r) => r.complianceStatus === 'missing').length,
    na:        requirements.filter((r) => r.complianceStatus === 'na').length,
  }

  return { filtered, counts, filter, setFilter, ...rest }
}

// ─── use-profile.ts ───────────────────────────────────────────────────────────
import { profileApi } from '@/lib/api'
import { MOCK_PROFILE } from '@/lib/constants/mock-data'
import type { CompanyProfile } from '@/types'

export function useProfile() {
  return useQuery({
    queryKey: ['profile'],
    queryFn: profileApi.get,
    placeholderData: MOCK_PROFILE,
  })
}

export function useSaveProfile() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (data: Partial<CompanyProfile>) => profileApi.save(data),
    onSuccess: (saved) => {
      qc.setQueryData(['profile'], saved)  // reflect the persisted profile immediately
    },
  })
}

// ─── use-processing.ts ────────────────────────────────────────────────────────
import { useEffect, useRef } from 'react'
import type { Pipeline } from '@/types'
import { MOCK_PIPELINE } from '@/lib/constants/mock-data'
import { useAuthStore } from '@/lib/stores/auth-store'

export function useProcessing(
  proposalId: string,
  onComplete?: () => void
) {
  const [pipeline, setPipeline] = useState<Pipeline>(MOCK_PIPELINE)
  const esRef = useRef<EventSource | null>(null)

  useEffect(() => {
    if (!proposalId) return

    const apiUrl = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'
    // EventSource can't set an Authorization header, so pass the JWT as a query
    // param — the backend scopes the stream to the owning tenant when present.
    const token = useAuthStore.getState().accessToken
    const url = `${apiUrl}/proposals/${proposalId}/pipeline/stream${token ? `?token=${encodeURIComponent(token)}` : ''}`
    const es = new EventSource(url)
    esRef.current = es

    es.onmessage = (e) => {
      try {
        const data: Pipeline = JSON.parse(e.data)
        setPipeline(data)
        if (data.status === 'completed') {
          es.close()
          onComplete?.()
        }
      } catch {}
    }

    es.onerror = () => es.close()

    return () => {
      es.close()
      esRef.current = null
    }
  }, [proposalId])

  return pipeline
}

// ─── use-upload.ts ────────────────────────────────────────────────────────────
import { documentsApi } from '@/lib/api'

export function useUpload() {
  const [uploading, setUploading] = useState(false)
  const [progress, setProgress] = useState(0)
  const [error, setError] = useState<string | null>(null)

  async function upload(file: File) {
    setUploading(true)
    setError(null)
    setProgress(0)
    try {
      // Tenancy is derived from the auth token attached by the axios client.
      const result = await documentsApi.upload(file, setProgress)
      return result
    } catch (e: any) {
      setError(e?.response?.data?.detail || 'Upload failed')
      throw e
    } finally {
      setUploading(false)
    }
  }

  return { upload, uploading, progress, error }
}
// ─── use-workspace-mutations.ts (Sprint 3) ────────────────────────────────────
// requirementsApi / sectionsApi are already imported above.
import { useMutation, useQueryClient } from '@tanstack/react-query'
import type { Requirement, ProposalSection } from '@/types'

export function useUpdateRequirement(proposalId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, patch }: { id: string; patch: Partial<Requirement> }) =>
      requirementsApi.update(id, patch),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['requirements', proposalId] }),
  })
}

export function useDeleteRequirement(proposalId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => requirementsApi.delete(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['requirements', proposalId] }),
  })
}

export function useGenerateSection(proposalId: string) {
  const qc = useQueryClient()
  return useMutation<ProposalSection, unknown, string>({
    mutationFn: (requirementId: string) => sectionsApi.generate(proposalId, requirementId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['sections', proposalId] }),
  })
}

export function useSaveSection(proposalId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, content }: { id: string; content: string }) =>
      sectionsApi.update(id, content),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['sections', proposalId] }),
  })
}

// ─── use-export-download.ts ───────────────────────────────────────────────────
import { exportApi } from '@/lib/api'
import type { ExportFormat } from '@/types'

/** Drives the full export flow imperatively: create job → poll until ready →
 *  download the blob → trigger a browser save. */
export function useExportDownload() {
  const [status, setStatus] = useState<'idle' | 'working' | 'failed'>('idle')
  const [error, setError] = useState<string | null>(null)

  async function download(proposalId: string, format: ExportFormat) {
    setError(null)
    setStatus('working')
    try {
      let job = await exportApi.create(proposalId, format)

      // Poll the job until the worker finishes rendering (cap at ~60s).
      const startedAt = Date.now()
      while (job.status !== 'ready' && job.status !== 'failed') {
        if (Date.now() - startedAt > 60_000) throw new Error('Export timed out — please try again.')
        await new Promise((r) => setTimeout(r, 1000))
        job = await exportApi.get(job.id)
      }
      if (job.status === 'failed' || !job.downloadUrl) throw new Error('Export generation failed.')

      const blob = await exportApi.download(job.downloadUrl)
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = `proposal-${proposalId}.${format}`
      document.body.appendChild(link)
      link.click()
      link.remove()
      URL.revokeObjectURL(url)
      setStatus('idle')
    } catch (e) {
      const err = e as { response?: { data?: { detail?: string } }; message?: string }
      setError(err.response?.data?.detail || err.message || 'Export failed.')
      setStatus('failed')
    }
  }

  return { download, status, error }
}
