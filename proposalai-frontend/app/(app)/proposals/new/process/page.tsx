'use client'
import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import { CheckCircle2, Loader2, Circle, ArrowRight, Clock } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, StepIndicator } from '@/components/ui/card'
import { MOCK_PIPELINE } from '@/lib/constants/mock-data'
import { cn } from '@/lib/utils/cn'
import type { PipelineStep } from '@/types'
import type { Step } from '@/components/ui/card'

const STEPS: Step[] = [
  { label: 'Upload RFP', status: 'done' },
  { label: 'Analyze',    status: 'done' },
  { label: 'Process',    status: 'active' },
  { label: 'Review',     status: 'pending' },
]

export default function ProcessPage() {
  const router = useRouter()
  const [progress, setProgress] = useState(64)
  const [statusMsg, setStatusMsg] = useState(MOCK_PIPELINE.statusMessage || '')

  // Simulate progress ticking up
  useEffect(() => {
    const msgs = [
      'Optimizing vector embeddings for better retrieval...',
      'Generating executive summary draft...',
      'Mapping compliance requirements to sections...',
      'Finalizing proposal structure...',
    ]
    let i = 0
    const interval = setInterval(() => {
      setProgress((p) => Math.min(p + 4, 100))
      setStatusMsg(msgs[i % msgs.length])
      i++
    }, 1200)
    return () => clearInterval(interval)
  }, [])

  function StepIcon({ step }: { step: PipelineStep }) {
    if (step.status === 'completed') return <CheckCircle2 className="w-5 h-5 text-success-400" />
    if (step.status === 'running')   return <Loader2 className="w-5 h-5 text-primary-600 animate-spin" />
    return <Circle className="w-5 h-5 text-[var(--text-tertiary)]" />
  }

  return (
    <div className="min-h-[calc(100vh-44px)] bg-[var(--bg-secondary)] flex flex-col items-center pt-12 px-4">
      <div className="w-full max-w-lg">
        <StepIndicator steps={STEPS} className="mb-8" />

        <Card className="mb-4">
          <div className="flex items-center gap-2 mb-1">
            <Loader2 className="w-4 h-4 text-primary-600 animate-spin" />
            <h2 className="text-sm font-medium">Processing document...</h2>
          </div>
          <p className="text-xs text-[var(--text-tertiary)] flex items-center gap-1 mb-5">
            <Clock className="w-3 h-3" /> Estimated completion: 20-40 seconds
          </p>

          <div className="space-y-3">
            {MOCK_PIPELINE.steps.map((step) => (
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
            <Button variant="default" size="sm" icon={<ArrowRight className="w-3.5 h-3.5" />} iconPosition="right" onClick={() => router.push('/proposals/1/workspace')}>
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
                  left: `${Math.random() * 100}%`,
                  top:  `${Math.random() * 100}%`,
                  animation: `pulse ${1 + Math.random() * 2}s ease-in-out infinite`,
                  animationDelay: `${Math.random()}s`,
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