'use client'
import { useRouter } from 'next/navigation'
import { CheckCircle2, ArrowLeft } from 'lucide-react'
import Link from 'next/link'
import { Button } from '@/components/ui/button'
import { Card, StepIndicator } from '@/components/ui/card'
import type { Step } from '@/components/ui/card'

const STEPS: Step[] = [
  { label: 'Upload RFP', status: 'done' },
  { label: 'Analyze',    status: 'done' },
  { label: 'Process',    status: 'done' },
  { label: 'Review',     status: 'active' },
]

const SUMMARY = [
  { label: 'Solicitation',         value: 'FA823-24-R-0012 — Enterprise Cloud Migration' },
  { label: 'Agency',               value: 'Department of Defense (DoD)' },
  { label: 'Contract type',        value: 'Firm Fixed Price (FFP)' },
  { label: 'Requirements found',   value: '34 (22 mandatory)' },
  { label: 'Sections to generate', value: '8 sections' },
  { label: 'Past performance used',value: '2 contracts matched' },
  { label: 'Drafting level',       value: 'Technical' },
  { label: 'Tone',                 value: 'Authoritative & Precise' },
]

export default function ReviewPage() {
  const router = useRouter()

  return (
    <div className="content-narrow">
      <StepIndicator steps={STEPS} className="mb-6" />

      <h1 className="text-lg font-medium mb-1">Review &amp; confirm</h1>
      <p className="text-xs text-[var(--text-secondary)] mb-5">Everything looks good. Confirm to open the workspace.</p>

      <Card className="mb-4">
        <h3 className="text-xs font-medium mb-3">Proposal summary</h3>
        <div className="flex flex-col divide-y divide-[var(--border-subtle)]">
          {SUMMARY.map((row) => (
            <div key={row.label} className="flex items-center justify-between py-2">
              <span className="text-xs text-[var(--text-secondary)]">{row.label}</span>
              <span className="text-xs font-medium text-right max-w-[60%]">{row.value}</span>
            </div>
          ))}
        </div>
      </Card>

      <Card className="mb-6">
        <div className="flex items-center gap-3">
          <CheckCircle2 className="w-5 h-5 text-success-400 shrink-0" />
          <div>
            <p className="text-xs font-medium">Ready to generate</p>
            <p className="text-xs text-[var(--text-tertiary)]">
              The AI will draft all 8 sections grounded in your company profile and matched past performance. You review and approve each section before exporting.
            </p>
          </div>
        </div>
      </Card>

      <div className="flex justify-between">
        <Button variant="default" icon={<ArrowLeft className="w-3.5 h-3.5" />} asChild>
          <Link href="/proposals/new/process">Back</Link>
        </Button>
        <Button variant="primary" onClick={() => router.push('/proposals/1/workspace')}>
          Open workspace →
        </Button>
      </div>
    </div>
  )
}