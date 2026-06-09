'use client'
import { useState, use } from 'react'
import { CheckCircle2, AlertCircle, XCircle, Download, ArrowLeft, Lock, FileText, FileSpreadsheet, Archive } from 'lucide-react'
import Link from 'next/link'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { MOCK_INTEGRITY_ITEMS } from '@/lib/constants/mock-data'
import { cn } from '@/lib/utils/cn'
import type { ExportFormat, IntegrityStatus } from '@/types'

const FORMATS: { id: ExportFormat; label: string; desc: string; icon: React.ReactNode }[] = [
  { id: 'pdf',  label: 'PDF',   desc: 'Universal', icon: <FileText className="w-6 h-6 text-primary-600" /> },
  { id: 'docx', label: 'Word',  desc: 'Editable',  icon: <FileText className="w-6 h-6 text-neutral-400" /> },
  { id: 'xlsx', label: 'Excel', desc: 'Data Only', icon: <FileSpreadsheet className="w-6 h-6 text-success-400" /> },
  { id: 'zip',  label: 'ZIP',   desc: 'All Files', icon: <Archive className="w-6 h-6 text-warning-400" /> },
]

function IntegrityIcon({ status }: { status: IntegrityStatus }) {
  if (status === 'verified')        return <CheckCircle2 className="w-4 h-4 text-success-400 shrink-0" />
  if (status === 'review_required') return <AlertCircle  className="w-4 h-4 text-warning-400 shrink-0" />
  return <XCircle className="w-4 h-4 text-danger-400 shrink-0" />
}

function integrityLabel(status: IntegrityStatus) {
  if (status === 'verified')        return { text: 'Verified',        cls: 'text-neutral-400' }
  if (status === 'review_required') return { text: 'Review Required', cls: 'text-warning-400' }
  return { text: 'Missing', cls: 'text-danger-600 font-medium' }
}

const totalIssues = MOCK_INTEGRITY_ITEMS.filter((i) => i.status !== 'verified').length
const complete    = Math.round((MOCK_INTEGRITY_ITEMS.filter((i) => i.status === 'verified').length / MOCK_INTEGRITY_ITEMS.length) * 100)

export default function ExportPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params)
  const [selectedFormat, setSelectedFormat] = useState<ExportFormat>('pdf')

  return (
    <div className="min-h-screen bg-neutral-50 flex flex-col items-center pt-12 px-4">
      <div className="w-full max-w-xl">
        <h1 className="text-xl font-medium text-center text-neutral-800 mb-1">Final Review & Export</h1>
        <p className="text-xs text-neutral-400 text-center mb-8">Verify all compliance checkpoints before generating final proposal files.</p>

        <Card className="mb-4">
          <div className="flex items-center justify-between mb-4">
            <p className="text-[10px] font-medium text-neutral-400 tracking-wider uppercase">Proposal Integrity Check</p>
            <span className={cn('text-xs font-medium px-2 py-0.5 rounded', complete >= 90 ? 'bg-success-50 text-success-600' : 'bg-neutral-100 text-neutral-500')}>
              {complete}% Complete
            </span>
          </div>
          <div className="space-y-2.5">
            {MOCK_INTEGRITY_ITEMS.map((item) => {
              const { text, cls } = integrityLabel(item.status)
              return (
                <div key={item.id} className="flex items-center justify-between gap-3">
                  <div className="flex items-center gap-2.5">
                    <IntegrityIcon status={item.status} />
                    <span className="text-xs text-neutral-700">{item.label}</span>
                  </div>
                  <span className={cn('text-xs shrink-0', cls)}>{text}</span>
                </div>
              )
            })}
          </div>
          {totalIssues > 0 && (
            <div className="mt-4 px-3 py-2.5 bg-warning-50 border border-warning-100 rounded-lg text-xs text-warning-600">
              {totalIssues} item{totalIssues > 1 ? 's' : ''} need attention.{' '}
              <Link href={`/proposals/${id}/compliance`} className="underline hover:no-underline">Review in Compliance Matrix</Link>
            </div>
          )}
        </Card>

        <Card className="mb-6">
          <p className="text-[10px] font-medium text-neutral-400 tracking-wider uppercase mb-3">Select Export Format</p>
          <div className="grid grid-cols-4 gap-3">
            {FORMATS.map((f) => (
              <button
                key={f.id}
                onClick={() => setSelectedFormat(f.id)}
                className={cn(
                  'flex flex-col items-center gap-2 p-3 rounded-lg border text-center transition-colors',
                  selectedFormat === f.id ? 'border-primary-600 bg-primary-50' : 'border-neutral-200 hover:border-neutral-400'
                )}
              >
                {f.icon}
                <div>
                  <p className="text-xs font-medium text-neutral-800">{f.label}</p>
                  <p className="text-[10px] text-neutral-400">{f.desc}</p>
                </div>
              </button>
            ))}
          </div>
        </Card>

        <div className="flex items-center justify-between mb-6">
          <Button variant="default" icon={<ArrowLeft className="w-3.5 h-3.5" />} asChild>
            <Link href={`/proposals/${id}/workspace`}>Back to editing</Link>
          </Button>
          <Button variant="primary" icon={<Download className="w-3.5 h-3.5" />}>Download export</Button>
        </div>

        <p className="flex items-center justify-center gap-1.5 text-[10px] text-neutral-400">
          <Lock className="w-3 h-3" /> Secure AES-256 encryption applied to all generated assets.
        </p>
      </div>
    </div>
  )
}