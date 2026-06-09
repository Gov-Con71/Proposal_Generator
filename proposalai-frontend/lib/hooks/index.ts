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

export function useProfile() {
  return useQuery({
    queryKey: ['profile'],
    queryFn: profileApi.get,
    placeholderData: MOCK_PROFILE,
  })
}

// ─── use-processing.ts ────────────────────────────────────────────────────────
import { useEffect, useRef } from 'react'
import type { Pipeline } from '@/types'
import { MOCK_PIPELINE } from '@/lib/constants/mock-data'

export function useProcessing(
  proposalId: string,
  onComplete?: () => void
) {
  const [pipeline, setPipeline] = useState<Pipeline>(MOCK_PIPELINE)
  const esRef = useRef<EventSource | null>(null)

  useEffect(() => {
    if (!proposalId) return

    const apiUrl = process.env.NEXT_PUBLIC_API_URL
    const es = new EventSource(`${apiUrl}/proposals/${proposalId}/pipeline/stream`)
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

  async function upload(file: File, proposalId: string) {
    setUploading(true)
    setError(null)
    setProgress(0)
    try {
      const result = await documentsApi.upload(file, proposalId, setProgress)
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