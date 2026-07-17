'use client'
import { use, useState } from 'react'
import { Download, RefreshCw, Trash2, ArrowUpDown } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { StatusDot } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { ErrorState } from '@/components/ui/state'
import { useRequirements, useUpdateRequirement, useDeleteRequirement } from '@/lib/hooks'
import { cn } from '@/lib/utils/cn'
import type { ComplianceStatus } from '@/types'

const STATUS_OPTIONS: ComplianceStatus[] = ['addressed', 'partial', 'missing', 'na']
type SortKey = 'number' | 'section' | 'category' | 'complianceStatus'

const FILTERS: { label: string; value: ComplianceStatus | 'all' }[] = [
  { label: 'All Requirements', value: 'all' },
  { label: 'Addressed',        value: 'addressed' },
  { label: 'Partial',          value: 'partial' },
  { label: 'Missing',          value: 'missing' },
  { label: 'N/A',              value: 'na' },
]

const CATEGORY_COLORS: Record<string, string> = {
  scope:            'bg-[var(--bg-secondary)] text-[var(--text-secondary)]',
  technical:        'bg-[var(--bg-secondary)] text-[var(--text-secondary)]',
  testing:          'bg-[var(--bg-secondary)] text-[var(--text-secondary)]',
  quality_assurance:'bg-[var(--bg-secondary)] text-[var(--text-secondary)]',
  packaging:        'bg-[var(--bg-secondary)] text-[var(--text-secondary)]',
  marking:          'bg-[var(--bg-secondary)] text-[var(--text-secondary)]',
  admin:            'bg-[var(--bg-secondary)] text-[var(--text-secondary)]',
  reporting:        'bg-[var(--bg-secondary)] text-[var(--text-secondary)]',
}

export default function CompliancePage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params)
  const [filter, setFilter] = useState<ComplianceStatus | 'all'>('all')
  const [search, setSearch] = useState('')

  // Requirements extracted by the Sprint 2 ingestion pipeline.
  const { data: requirements = [], isLoading, isError, error, refetch } = useRequirements(id)
  const updateReq = useUpdateRequirement(id)
  const deleteReq = useDeleteRequirement(id)
  const [sortKey, setSortKey] = useState<SortKey>('number')
  const [sortAsc, setSortAsc] = useState(true)

  function toggleSort(key: SortKey) {
    if (key === sortKey) setSortAsc((a) => !a)
    else { setSortKey(key); setSortAsc(true) }
  }

  const counts = {
    all:       requirements.length,
    addressed: requirements.filter((r) => r.complianceStatus === 'addressed').length,
    partial:   requirements.filter((r) => r.complianceStatus === 'partial').length,
    missing:   requirements.filter((r) => r.complianceStatus === 'missing').length,
    na:        requirements.filter((r) => r.complianceStatus === 'na').length,
  }

  const filtered = requirements.filter((r) => {
    const matchFilter = filter === 'all' || r.complianceStatus === filter
    const matchSearch = !search || r.text.toLowerCase().includes(search.toLowerCase()) || r.section.toLowerCase().includes(search.toLowerCase())
    return matchFilter && matchSearch
  })

  const sorted = [...filtered].sort((a, b) => {
    const av = a[sortKey] as string | number
    const bv = b[sortKey] as string | number
    const an = typeof av === 'string' ? av.toLowerCase() : av
    const bn = typeof bv === 'string' ? bv.toLowerCase() : bv
    if (an < bn) return sortAsc ? -1 : 1
    if (an > bn) return sortAsc ? 1 : -1
    return 0
  })

  return (
    <div className="page-padding">
      {/* Header */}
      <div className="flex items-start justify-between mb-4">
        <div>
          <h1 className="text-lg font-medium">Compliance Matrix</h1>
          <div className="flex items-center gap-2 mt-0.5">
            <span className="text-xs text-[var(--text-secondary)] font-medium">RFP-2024-USCG-4914</span>
            <span className="text-[var(--text-tertiary)]">·</span>
            <span className="text-xs text-[var(--text-tertiary)]">Last updated: {new Date().toLocaleString()}</span>
          </div>
        </div>
        <div className="flex gap-2">
          <Button variant="default" size="sm" icon={<Download className="w-3.5 h-3.5" />}>Export PDF</Button>
          <Button variant="primary" size="sm" icon={<RefreshCw className="w-3.5 h-3.5" />}>Re-analyze RFP</Button>
        </div>
      </div>

      {/* Filters + search */}
      <div className="flex items-center gap-2 mb-4 flex-wrap">
        {FILTERS.map((f) => (
          <button
            key={f.value}
            onClick={() => setFilter(f.value)}
            className={cn(
              'inline-flex items-center gap-1.5 px-3 py-1 rounded-full border text-xs transition-colors',
              filter === f.value
                ? 'bg-primary-50 border-primary-100 text-primary-800 font-medium'
                : 'bg-[var(--bg-primary)] border-[var(--border-default)] text-[var(--text-secondary)] hover:border-[var(--border-strong)]'
            )}
          >
            {f.value !== 'all' && <StatusDot status={f.value as ComplianceStatus} />}
            {f.label}
            <span className={cn(
              'ml-0.5 px-1.5 py-0.5 rounded-full text-[10px] font-medium',
              f.value === 'missing' && counts.missing > 0 ? 'bg-danger-50 text-danger-600' : 'bg-[var(--bg-secondary)] text-[var(--text-tertiary)]'
            )}>
              {counts[f.value]}
            </span>
          </button>
        ))}
        <div className="ml-auto w-52">
          <Input placeholder="Search requirement text..." value={search} onChange={(e) => setSearch(e.target.value)} />
        </div>
      </div>

      {/* Table */}
      <Card padding="none" className="overflow-hidden">
        <table className="w-full text-xs border-collapse">
          <thead>
            <tr className="bg-[var(--bg-secondary)]">
              {([
                ['#', 'number'], ['SECTION', 'section'], ['REQUIREMENT TEXT', null],
                ['CATEGORY', 'category'], ['TYPE', null], ['STATUS', 'complianceStatus'], ['', null],
              ] as [string, SortKey | null][]).map(([label, key], i) => (
                <th
                  key={i}
                  onClick={() => key && toggleSort(key)}
                  className={cn(
                    'text-left text-[10px] font-medium text-[var(--text-tertiary)] tracking-wider px-3 py-2.5 border-b border-[var(--border-subtle)]',
                    key && 'cursor-pointer select-none hover:text-[var(--text-secondary)]'
                  )}
                >
                  <span className="inline-flex items-center gap-1">
                    {label}
                    {key && <ArrowUpDown className={cn('w-3 h-3', sortKey === key ? 'text-primary-600' : 'opacity-30')} />}
                  </span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {isLoading && [...Array(6)].map((_, i) => (
              <tr key={`sk-${i}`} className="border-b border-[var(--border-subtle)]">
                {[...Array(7)].map((__, j) => (
                  <td key={j} className="px-3 py-3">
                    <div className="h-3 rounded bg-[var(--bg-secondary)] animate-pulse" />
                  </td>
                ))}
              </tr>
            ))}
            {!isLoading && !isError && sorted.length === 0 && (
              <tr>
                <td colSpan={7} className="px-3 py-8 text-center text-[var(--text-tertiary)]">
                  {requirements.length === 0
                    ? 'No requirements extracted for this document yet.'
                    : 'No requirements match the current filter.'}
                </td>
              </tr>
            )}
            {!isLoading && sorted.map((req) => (
              <tr key={req.id} className="border-b border-[var(--border-subtle)] last:border-0 hover:bg-[var(--bg-secondary)] transition-colors">
                <td className="px-3 py-2.5 text-[var(--text-tertiary)]">{String(req.number).padStart(3, '0')}</td>
                <td className="px-3 py-2.5 text-primary-600 font-medium">{req.section}</td>
                <td className="px-3 py-2.5 text-[var(--text-primary)] max-w-[280px]">
                  <span className="truncate-2">{req.text}</span>
                </td>
                <td className="px-3 py-2.5">
                  <span className={cn('px-1.5 py-0.5 rounded text-[10px] capitalize', CATEGORY_COLORS[req.category] || 'bg-[var(--bg-secondary)] text-[var(--text-secondary)]')}>
                    {req.category.replace(/_/g, ' ')}
                  </span>
                </td>
                <td className="px-3 py-2.5">
                  <span className={cn('text-[10px] font-medium uppercase tracking-wider', req.type === 'mandatory' ? 'text-danger-600' : 'text-[var(--text-tertiary)]')}>
                    {req.type}
                  </span>
                </td>
                {/* Inline-editable status */}
                <td className="px-3 py-2.5">
                  <div className="flex items-center gap-1.5">
                    <StatusDot status={req.complianceStatus as ComplianceStatus} />
                    <select
                      value={req.complianceStatus}
                      disabled={updateReq.isPending}
                      onChange={(e) => updateReq.mutate({ id: req.id, patch: { complianceStatus: e.target.value as ComplianceStatus } })}
                      className="bg-transparent text-xs capitalize border border-transparent hover:border-[var(--border-default)] rounded px-1 py-0.5 cursor-pointer focus:outline-none focus:border-primary-600"
                    >
                      {STATUS_OPTIONS.map((s) => (
                        <option key={s} value={s}>{s === 'na' ? 'N/A' : s}</option>
                      ))}
                    </select>
                  </div>
                </td>
                {/* Delete */}
                <td className="px-3 py-2.5 text-right">
                  <button
                    onClick={() => { if (confirm('Delete this requirement?')) deleteReq.mutate(req.id) }}
                    disabled={deleteReq.isPending}
                    title="Delete requirement"
                    className="text-[var(--text-tertiary)] hover:text-danger-600 transition-colors disabled:opacity-40"
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>

        {isError && (
          <ErrorState title="Could not load the compliance matrix" error={error} onRetry={() => refetch()} />
        )}
      </Card>

      {/* Status bar */}
      <div className="flex items-center justify-between mt-3 px-1">
        <div className="flex items-center gap-2 text-[10px] text-success-600">
          <div className="w-1.5 h-1.5 rounded-full bg-success-400 animate-pulse" />
          Analysis Synchronized · Detected requirements: {requirements.length}
        </div>
        <span className="text-[10px] text-[var(--text-tertiary)]">Compute Engine v4.2.0-stable</span>
      </div>
    </div>
  )
}