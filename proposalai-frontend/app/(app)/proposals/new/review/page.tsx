'use client'
import { use } from 'react'
import { useRouter } from 'next/navigation'
import { CheckCircle2, AlertCircle, ArrowLeft } from 'lucide-react'
import Link from 'next/link'
import { Button } from '@/components/ui/button'
import { Card, Skeleton, StepIndicator } from '@/components/ui/card'
import { EmptyState, ErrorState } from '@/components/ui/state'
import { useDocumentStatus, useRequirements, useSections, useProfile } from '@/lib/hooks'
import type { Step } from '@/components/ui/card'

const STEPS: Step[] = [
  { label: 'Upload RFP', status: 'done' },
  { label: 'Analyze',    status: 'done' },
  { label: 'Process',    status: 'done' },
  { label: 'Review',     status: 'active' },
]

export default function ReviewPage({ searchParams }: { searchParams: Promise<{ rfp?: string }> }) {
  const router = useRouter()
  const { rfp } = use(searchParams)
  const id = rfp ?? ''

  const document = useDocumentStatus(id)
  const requirements = useRequirements(id)
  const sections = useSections(id)
  const profile = useProfile()

  // Reaching review without an rfp id means the flow lost the uploaded document.
  if (!rfp) {
    return (
      <div className="content-narrow">
        <StepIndicator steps={STEPS} className="mb-6" />
        <Card>
          <EmptyState
            title="No document to review"
            message="This step summarises an ingested RFP. Start from the upload page."
            action={
              <Button variant="primary" size="sm" onClick={() => router.push('/proposals/new')}>
                Upload an RFP
              </Button>
            }
          />
        </Card>
      </div>
    )
  }

  const isLoading = document.isLoading || requirements.isLoading
  const failed = document.isError || requirements.isError

  if (failed) {
    return (
      <div className="content-narrow">
        <StepIndicator steps={STEPS} className="mb-6" />
        <Card>
          <ErrorState
            title="Could not load the proposal summary"
            error={document.error ?? requirements.error}
            onRetry={() => { document.refetch(); requirements.refetch() }}
          />
        </Card>
      </div>
    )
  }

  const reqs = requirements.data ?? []
  const mandatory = reqs.filter((r) => r.type === 'mandatory').length
  const pastPerformance = profile.data?.pastPerformance.length ?? 0
  const drafted = sections.data?.length ?? 0

  // Only rows backed by real data. Solicitation, agency, contract type and tone
  // live on a `proposals` row, which uploading an RFP doesn't create yet — so
  // they're deliberately absent rather than invented.
  const summary: { label: string; value: string }[] = [
    { label: 'Document',            value: document.data?.fileName ?? '—' },
    { label: 'Ingestion status',    value: document.data?.processingStatus ?? '—' },
    { label: 'Requirements found',  value: `${reqs.length}${reqs.length ? ` (${mandatory} mandatory)` : ''}` },
    { label: 'Sections drafted',    value: String(drafted) },
    { label: 'Past performance on file', value: `${pastPerformance} contract${pastPerformance === 1 ? '' : 's'}` },
  ]

  const ready = reqs.length > 0

  return (
    <div className="content-narrow">
      <StepIndicator steps={STEPS} className="mb-6" />

      <h1 className="text-lg font-medium mb-1">Review &amp; confirm</h1>
      <p className="text-xs text-[var(--text-secondary)] mb-5">
        What the ingestion pipeline extracted from your RFP. Confirm to open the workspace.
      </p>

      <Card className="mb-4">
        <h3 className="text-xs font-medium mb-3">Proposal summary</h3>
        {isLoading ? (
          <div className="flex flex-col gap-3">
            {Array.from({ length: 5 }).map((_, i) => <Skeleton key={i} height={14} />)}
          </div>
        ) : (
          <div className="flex flex-col divide-y divide-[var(--border-subtle)]">
            {summary.map((row) => (
              <div key={row.label} className="flex items-center justify-between py-2">
                <span className="text-xs text-[var(--text-secondary)]">{row.label}</span>
                <span className="text-xs font-medium text-right max-w-[60%]">{row.value}</span>
              </div>
            ))}
          </div>
        )}
      </Card>

      {!isLoading && (
        <Card className="mb-6">
          <div className="flex items-center gap-3">
            {ready
              ? <CheckCircle2 className="w-5 h-5 text-success-400 shrink-0" />
              : <AlertCircle className="w-5 h-5 text-warning-400 shrink-0" />}
            <div>
              <p className="text-xs font-medium">{ready ? 'Ready to generate' : 'Nothing to generate yet'}</p>
              <p className="text-xs text-[var(--text-tertiary)]">
                {ready
                  ? `The AI drafts against these ${reqs.length} requirements, grounded in your company profile and matched past performance. You review and approve each section before exporting.`
                  : 'No requirements were extracted from this document, so there is nothing to draft against. Re-run the analysis from the workspace.'}
              </p>
            </div>
          </div>
        </Card>
      )}

      <div className="flex justify-between">
        <Button variant="default" icon={<ArrowLeft className="w-3.5 h-3.5" />} asChild>
          <Link href={`/proposals/new/process?rfp=${rfp}`}>Back</Link>
        </Button>
        <Button variant="primary" onClick={() => router.push(`/proposals/${rfp}/workspace`)}>
          Open workspace →
        </Button>
      </div>
    </div>
  )
}
