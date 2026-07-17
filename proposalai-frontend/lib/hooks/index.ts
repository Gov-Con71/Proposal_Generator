// ─── use-proposals.ts ─────────────────────────────────────────────────────────
import { useQuery } from '@tanstack/react-query'
import { proposalsApi } from '@/lib/api'

// A valid id is required before any of the per-proposal queries may run. Next's
// dynamic params arrive as strings, so a missing one shows up as "undefined"
// rather than a falsy value — which would otherwise be requested verbatim.
export function isValidId(id: string | undefined | null): id is string {
  return !!id && id !== 'undefined' && id !== 'null'
}

export function useProposals() {
  return useQuery({
    queryKey: ['proposals'],
    queryFn: proposalsApi.list,
  })
}

// ─── use-proposal.ts ──────────────────────────────────────────────────────────
export function useProposal(id: string) {
  return useQuery({
    queryKey: ['proposals', id],
    queryFn: () => proposalsApi.get(id),
    enabled: isValidId(id),
  })
}

// ─── use-requirements.ts ──────────────────────────────────────────────────────
import { requirementsApi } from '@/lib/api'

export function useRequirements(proposalId: string) {
  return useQuery({
    queryKey: ['requirements', proposalId],
    queryFn: () => requirementsApi.list(proposalId),
    enabled: isValidId(proposalId),
  })
}

// ─── use-sections.ts ──────────────────────────────────────────────────────────
import { sectionsApi } from '@/lib/api'

export function useSections(proposalId: string) {
  return useQuery({
    queryKey: ['sections', proposalId],
    queryFn: () => sectionsApi.list(proposalId),
    enabled: isValidId(proposalId),
  })
}

// ─── use-document-status.ts ───────────────────────────────────────────────────
import { documentsApi } from '@/lib/api'

/** Ingestion state for an uploaded RFP: file name, status, requirement count. */
export function useDocumentStatus(rfpId: string) {
  return useQuery({
    queryKey: ['documents', rfpId],
    queryFn: () => documentsApi.status(rfpId),
    enabled: isValidId(rfpId),
  })
}

// ─── use-integrity.ts ─────────────────────────────────────────────────────────
import { integrityApi } from '@/lib/api'

export function useIntegrity(proposalId: string) {
  return useQuery({
    queryKey: ['integrity', proposalId],
    queryFn: () => integrityApi.list(proposalId),
    enabled: isValidId(proposalId),
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
import type { CompanyProfile } from '@/types'

export function useProfile() {
  return useQuery({
    queryKey: ['profile'],
    queryFn: profileApi.get,
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
import { useAuthStore } from '@/lib/stores/auth-store'

/** Nothing has streamed yet. Rendered as "connecting", never as progress. */
const IDLE_PIPELINE: Pipeline = {
  proposalId: '',
  status: 'idle',
  overallProgress: 0,
  steps: [],
  startedAt: '',
}

export function useProcessing(proposalId: string, onComplete?: () => void) {
  const [pipeline, setPipeline] = useState<Pipeline>(IDLE_PIPELINE)
  const [connectionError, setConnectionError] = useState(false)
  const esRef = useRef<EventSource | null>(null)

  // Keep the latest callback without making it an effect dependency — otherwise
  // an inline arrow from the caller would tear down the stream on every render.
  const onCompleteRef = useRef(onComplete)
  useEffect(() => { onCompleteRef.current = onComplete })

  useEffect(() => {
    if (!isValidId(proposalId)) return

    setPipeline(IDLE_PIPELINE)
    setConnectionError(false)

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
        setConnectionError(false)
        if (data.status === 'completed') {
          es.close()
          onCompleteRef.current?.()
        }
      } catch {
        // A single malformed frame isn't fatal; keep the stream open.
      }
    }

    // Surface the dropped stream instead of hanging on a stale progress bar.
    es.onerror = () => {
      setConnectionError(true)
      es.close()
    }

    return () => {
      es.close()
      esRef.current = null
    }
  }, [proposalId])

  return { pipeline, connectionError }
}

// ─── use-upload.ts ────────────────────────────────────────────────────────────
// documentsApi is already imported above by use-document-status.

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
