'use client'
import { use } from 'react'
import { useRouter } from 'next/navigation'
import { CheckCircle2, Loader2, Circle, XCircle, ArrowRight, Clock } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, StepIndicator } from '@/components/ui/card'
import { PROPOSAL_STEPS } from '@/lib/constants/steps'
import { EmptyState, ErrorState } from '@/components/ui/state'
import { useProcessing } from '@/lib/hooks'
import { cn } from '@/lib/utils/cn'
import type { PipelineStep } from '@/types'


export default function ProcessPage({ searchParams }: { searchParams: Promise<{ proposal?: string }> }) {
  const router = useRouter()
  const { proposal } = use(searchParams)

  // Live ingestion progress for the uploaded RFP (SSE). On completion, hand off
  // to the review step, which summarises what was actually extracted.
  const { pipeline, connectionError } = useProcessing(proposal ?? '', () => {
    if (proposal) router.push(`/proposals/new/review?proposal=${proposal}`)
  })
  const progress = pipeline.overallProgress
  const statusMsg = pipeline.statusMessage ?? ''
  const connecting = pipeline.status === 'idle' && !connectionError

  function StepIcon({ step }: { step: PipelineStep }) {
    if (step.status === 'completed') return <CheckCircle2 className="w-5 h-5 text-success-400" />
    if (step.status === 'running')   return <Loader2 className="w-5 h-5 text-primary-600 animate-spin" />
    if (step.status === 'failed')    return <XCircle className="w-5 h-5 text-danger-600" />
    return <Circle className="w-5 h-5 text-[var(--text-tertiary)]" />
  }

  // Reaching this page without a proposal id means the upload handoff broke. Say so
  // rather than opening a stream against /proposals/undefined/….
  if (!proposal) {
    return (
      <div className="min-h-[calc(100vh-44px)] bg-[var(--bg-secondary)] flex items-center justify-center px-4">
        <Card className="w-full max-w-lg">
          <EmptyState
            title="No document to process"
            message="This step needs an uploaded RFP. Start from the upload page and try again."
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

  // A failed run is a real, explained outcome — render it before the connection
  // branch. The stream closes right after the failure frame, so the close that
  // follows must not be allowed to overwrite this with "lost connection".
  if (pipeline.status === 'failed') {
    return (
      <div className="min-h-[calc(100vh-44px)] bg-[var(--bg-secondary)] flex items-center justify-center px-4">
        <Card className="w-full max-w-lg">
          <ErrorState
            title="Processing failed"
            message={statusMsg || 'The RFP could not be processed.'}
          />
          <div className="flex justify-center gap-2 pb-4">
            <Button variant="primary" size="sm" onClick={() => router.push('/proposals/new')}>
              Upload another RFP
            </Button>
            <Button variant="default" size="sm" onClick={() => router.push(`/proposals/${proposal}/workspace`)}>
              Open workspace
            </Button>
          </div>
        </Card>
      </div>
    )
  }

  if (connectionError) {
    return (
      <div className="min-h-[calc(100vh-44px)] bg-[var(--bg-secondary)] flex items-center justify-center px-4">
        <Card className="w-full max-w-lg">
          <ErrorState
            title="Lost connection to the processing stream"
            message="The ingestion may still be running on the server. Reload to reconnect, or open the workspace to check."
            onRetry={() => window.location.reload()}
          />
          <div className="flex justify-center pb-4">
            <Button variant="default" size="sm" onClick={() => router.push(`/proposals/${proposal}/workspace`)}>
              Open workspace
            </Button>
          </div>
        </Card>
      </div>
    )
  }

  return (
    <div className="min-h-[calc(100vh-44px)] bg-[var(--bg-secondary)] flex flex-col items-center pt-12 px-4">
      <div className="w-full max-w-lg">
        <StepIndicator steps={PROPOSAL_STEPS('process')} className="mb-8" />

        <Card className="mb-4">
          <div className="flex items-center gap-2 mb-1">
            <Loader2 className="w-4 h-4 text-primary-600 animate-spin" />
            <h2 className="text-sm font-medium">
              {connecting ? 'Connecting to processing stream…' : 'Processing document...'}
            </h2>
          </div>
          <p className="text-xs text-[var(--text-tertiary)] flex items-center gap-1 mb-5">
            <Clock className="w-3 h-3" /> Estimated completion: 20-40 seconds
          </p>

          <div className="space-y-3">
            {pipeline.steps.map((step) => (
              <div key={step.id} className={cn(
                'flex items-center gap-3 py-2 px-3 rounded-lg',
                step.status === 'running' && 'bg-[var(--bg-secondary)]'
              )}>
                <StepIcon step={step} />
                <div className="flex-1">
                  <p className={cn('text-xs font-medium', step.status === 'pending' && 'text-[var(--text-tertiary)]')}>
                    {step.label}
                  </p>
                  {step.meta && <p className="text-[10px] text-[var(--text-tertiary)]">{step.meta}</p>}
                </div>
                <span className={cn(
                  'text-[10px] font-medium px-2 py-0.5 rounded',
                  step.status === 'completed' && 'bg-success-50 text-success-600',
                  step.status === 'running'   && 'bg-primary-50 text-primary-600',
                  step.status === 'pending'   && 'text-[var(--text-tertiary)]',
                )}>
                  {step.status === 'completed' ? 'Completed'
                   : step.status === 'running' ? 'Active'
                   : 'Pending'}
                </span>
              </div>
            ))}
          </div>

          <div className="mt-5">
            <div className="flex justify-between text-xs text-[var(--text-secondary)] mb-1.5">
              <span>Overall Progress</span>
              <span className="font-medium text-primary-600">{progress}%</span>
            </div>
            <div className="h-1.5 bg-[var(--bg-secondary)] rounded-full overflow-hidden">
              <div
                className="h-full bg-primary-600 rounded-full transition-all duration-500"
                style={{ width: `${progress}%` }}
              />
            </div>
          </div>

          <div className="flex justify-end mt-4">
            <Button variant="default" size="sm" icon={<ArrowRight className="w-3.5 h-3.5" />} iconPosition="right" onClick={() => router.push(proposal ? `/proposals/${proposal}/workspace` : '/dashboard')}>
              Skip to workspace
            </Button>
          </div>
        </Card>

        {/* Neural animation placeholder */}
        <div className="w-full h-48 rounded-xl bg-neutral-900 flex items-end justify-center p-4 overflow-hidden relative">
          <div className="absolute inset-0 flex items-center justify-center">
            {[...Array(20)].map((_, i) => (
              <div
                key={i}
                className="absolute w-1 h-1 bg-white rounded-full opacity-40"
                style={{
                  left: `${(i * 37 + 11) % 100}%`,
                  top:  `${(i * 61 + 23) % 100}%`,
                  animation: `pulse ${1 + (i % 5) / 2}s ease-in-out infinite`,
                  animationDelay: `${(i % 7) / 7}s`,
                }}
              />
            ))}
          </div>
          <div className="relative z-10 flex items-center gap-2 bg-neutral-800 rounded-full px-4 py-1.5">
            <div className="w-1.5 h-1.5 rounded-full bg-primary-400 animate-pulse" />
            <span className="text-[10px] text-white uppercase tracking-wider">Analyzing Compliance Matrix</span>
          </div>
        </div>

        {/* Status ticker */}
        <div className="mt-3 flex items-center gap-2 px-3 py-2 bg-neutral-900 rounded-full w-fit mx-auto">
          <div className="w-3.5 h-3.5 rounded-full border border-neutral-600 flex items-center justify-center">
            <span className="text-[8px] text-neutral-400">i</span>
          </div>
          <p className="text-[10px] text-neutral-400">{statusMsg}</p>
        </div>
      </div>
    </div>
  )
}