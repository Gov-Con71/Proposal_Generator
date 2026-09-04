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
import { authApi, profileApi } from '@/lib/api'
import type { CompanyProfile } from '@/types'

export function useProfile() {
  return useQuery({
    queryKey: ['profile'],
    queryFn: profileApi.get,
  })
}

export function useActiveSessions() {
  return useQuery({
    queryKey: ['sessions'],
    queryFn: authApi.getSessions,
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

/** Reconnect attempts before the drop is called fatal. Each costs a fresh
 *  ticket plus a stream open, spaced by RECONNECT_DELAY_MS. */
export const MAX_RECONNECTS = 5
export const RECONNECT_DELAY_MS = 3000

export function useProcessing(proposalId: string, onComplete?: () => void) {
  const [pipeline, setPipeline] = useState<Pipeline>(IDLE_PIPELINE)
  const [connectionError, setConnectionError] = useState(false)

  // Keep the latest callback without making it an effect dependency — otherwise
  // an inline arrow from the caller would tear down the stream on every render.
  const onCompleteRef = useRef(onComplete)
  useEffect(() => { onCompleteRef.current = onComplete })

  useEffect(() => {
    if (!isValidId(proposalId)) return

    setPipeline(IDLE_PIPELINE)
    setConnectionError(false)

    const apiUrl = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'
    let es: EventSource | null = null
    let timer: ReturnType<typeof setTimeout> | null = null
    let attempts = 0
    let done = false // terminal frame seen, or the effect was torn down

    // Reconnection is ours to drive now, not EventSource's.
    //
    // The stream is authorised by a single-use ticket, so the browser's own
    // automatic retry — which replays the identical URL — presents a spent
    // ticket and is rejected every time. Each attempt therefore has to mint a
    // fresh one, which means closing the socket on any error rather than
    // letting it retry itself into a guaranteed 401.
    async function connect() {
      if (done) return
      try {
        const { ticket } = await documentsApi.streamTicket(proposalId)
        if (done) return
        es = new EventSource(
          `${apiUrl}/proposals/${proposalId}/pipeline/stream?ticket=${encodeURIComponent(ticket)}`
        )
      } catch {
        // Couldn't even get a ticket (signed out, 404, ticket store down).
        scheduleRetry()
        return
      }

      es.onmessage = (e) => {
        try {
          const data: Pipeline = JSON.parse(e.data)
          setPipeline(data)
          setConnectionError(false)
          attempts = 0 // a frame arrived: the stream is healthy again
          if (data.status === 'completed' || data.status === 'failed') {
            done = true
            es?.close()
            if (data.status === 'completed') onCompleteRef.current?.()
          }
        } catch {
          // A single malformed frame isn't fatal; keep the stream open.
        }
      }

      // Any interruption lands here: a genuine network drop, or the server
      // reaching its per-connection budget and closing a stream whose work is
      // still running. Neither is fatal on its own — treating them as fatal
      // stranded the page on an error screen for ingestions that went on to
      // succeed — so reconnect, bounded.
      es.onerror = () => {
        es?.close()
        scheduleRetry()
      }
    }

    function scheduleRetry() {
      if (done) return
      attempts += 1
      if (attempts > MAX_RECONNECTS) {
        setConnectionError(true)
        return
      }
      timer = setTimeout(connect, RECONNECT_DELAY_MS)
    }

    void connect()

    return () => {
      done = true
      if (timer) clearTimeout(timer)
      es?.close()
      es = null
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

/** Drives the full drafting agent imperatively: POST /proposals/{id}/draft →
 *  poll the proposal's draftingStatus until 'drafted' → refresh the sections.
 *
 *  Everything here is keyed on the proposal. It used to trigger on the proposal
 *  but poll the *document*, which reported whichever bid on that RFP wrote last
 *  — so a second proposal's draft could show as finished the moment the first
 *  one completed. Migration 0005 moved the flag onto the proposal; this follows
 *  it, and no longer needs the rfpId at all.
 *
 *  Drafting is many LLM calls (plan → per-section draft + compliance critique),
 *  so it can take minutes on a constrained provider quota — hence the generous
 *  poll cap. */
export function useGenerateDraft(proposalId: string) {
  const qc = useQueryClient()
  const [status, setStatus] = useState<'idle' | 'drafting' | 'failed'>('idle')
  const [error, setError] = useState<string | null>(null)

  async function generate() {
    if (!isValidId(proposalId)) return
    setError(null)
    setStatus('drafting')
    try {
      await documentsApi.draft(proposalId)
      // Poll until the worker finishes ('drafted') or fails ('draft_failed').
      // The POST has already set 'drafting', so the first read cannot race
      // ahead and see a previous run's terminal state.
      const startedAt = Date.now()
      let proposal = await proposalsApi.get(proposalId)
      while (proposal.draftingStatus === 'drafting') {
        if (Date.now() - startedAt > 15 * 60_000) {
          throw new Error('Drafting timed out — please try again.')
        }
        await new Promise((r) => setTimeout(r, 3000))
        proposal = await proposalsApi.get(proposalId)
      }
      // The server records *why* it failed; show that instead of a generic
      // message, which is the difference between "retry" and "fix your config".
      if (proposal.draftingStatus === 'draft_failed') {
        throw new Error(proposal.draftingFailureReason || 'Draft generation failed.')
      }
      qc.invalidateQueries({ queryKey: ['sections', proposalId] })
      qc.invalidateQueries({ queryKey: ['proposals', proposalId] })
      setStatus('idle')
    } catch (e) {
      const err = e as { response?: { data?: { detail?: string } }; message?: string }
      setError(err.response?.data?.detail || err.message || 'Draft generation failed.')
      setStatus('failed')
    }
  }

  return { generate, status, error }
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

// ─── use-history.ts (past-performance evidence) ───────────────────────────────
import { historyApi } from '@/lib/api'

/** Sources in ONE pool: the long-term library, or one bid's supporting docs.
 *  The pool is part of the query key, so the two pages never share a cache
 *  entry and switching between them can't show the wrong list. */
export function useHistorySources(proposalId?: string) {
  return useQuery({
    queryKey: ['history', proposalId ?? 'library'],
    queryFn: () => historyApi.list(proposalId),
  })
}

export function useHistoryUpload(proposalId?: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (file: File) => historyApi.upload(file, proposalId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['history', proposalId ?? 'library'] })
    },
  })
}

export function useHistoryRemove(proposalId?: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (sourceName: string) => historyApi.remove(sourceName, proposalId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['history', proposalId ?? 'library'] })
    },
  })
}

/** Moves one of THIS bid's supporting documents into the long-term library.
 *  `proposalId` optional only to mirror the sibling hooks' signature — the
 *  library page never renders the button that would call this, so the
 *  missing-id throw is unreachable in practice, not a real runtime path.
 *  Invalidates both caches: the source disappears from the bid's list and
 *  (if it's ever been fetched) reappears in the library's. */
export function useHistoryPromote(proposalId?: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (sourceName: string) => {
      if (!proposalId) throw new Error('useHistoryPromote requires a proposalId')
      return historyApi.promote(sourceName, proposalId)
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['history', proposalId ?? 'library'] })
      qc.invalidateQueries({ queryKey: ['history', 'library'] })
    },
  })
}
