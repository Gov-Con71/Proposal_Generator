'use client'
import { useState } from 'react'
import { Download, RefreshCw, Search } from 'lucide-react'
import Link from 'next/link'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { StatusDot } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { MOCK_REQUIREMENTS } from '@/lib/constants/mock-data'
import { cn } from '@/lib/utils/cn'
import type { ComplianceStatus } from '@/types'

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

export default function CompliancePage({ params }: { params: { id: string } }) {
  const [filter, setFilter] = useState<ComplianceStatus | 'all'>('all')
  const [search, setSearch] = useState('')

  const counts = {
    all:       MOCK_REQUIREMENTS.length,
    addressed: MOCK_REQUIREMENTS.filter((r) => r.complianceStatus === 'addressed').length,
    partial:   MOCK_REQUIREMENTS.filter((r) => r.complianceStatus === 'partial').length,
    missing:   MOCK_REQUIREMENTS.filter((r) => r.complianceStatus === 'missing').length,
    na:        MOCK_REQUIREMENTS.filter((r) => r.complianceStatus === 'na').length,
  }

  const filtered = MOCK_REQUIREMENTS.filter((r) => {
    const matchFilter = filter === 'all' || r.complianceStatus === filter
    const matchSearch = !search || r.text.toLowerCase().includes(search.toLowerCase()) || r.section.toLowerCase().includes(search.toLowerCase())
    return matchFilter && matchSearch
  })

  function confColor(score: number | null) {
    if (score === null) return 'text-danger-600 font-medium'
    if (score >= 90) return 'text-success-600'
    if (score >= 70) return 'text-warning-400'
    return 'text-danger-600 font-medium'
  }

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
              {['#', 'SECTION', 'REQUIREMENT TEXT', 'CATEGORY', 'TYPE', 'PROPOSAL LINK', 'STATUS', 'CONF.'].map((h) => (
                <th key={h} className="text-left text-[10px] font-medium text-[var(--text-tertiary)] tracking-wider px-3 py-2.5 border-b border-[var(--border-subtle)]">
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {filtered.map((req) => (
              <tr key={req.id} className="border-b border-[var(--border-subtle)] last:border-0 hover:bg-[var(--bg-secondary)] transition-colors">
                <td className="px-3 py-2.5 text-[var(--text-tertiary)]">{String(req.number).padStart(3, '0')}</td>
                <td className="px-3 py-2.5 text-primary-600 font-medium">{req.section}</td>
                <td className="px-3 py-2.5 text-[var(--text-primary)] max-w-[260px]">
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
                <td className="px-3 py-2.5">
                  {req.proposalSectionTitle ? (
                    <Link href={`/proposals/1/workspace`} className="text-primary-600 hover:text-primary-800 flex items-center gap-1 transition-colors">
                      <span className="text-[10px]">⟷</span> {req.proposalSectionTitle}
                    </Link>
                  ) : (
                    <span className="text-[var(--text-tertiary)]">—</span>
                  )}
                </td>
                <td className="px-3 py-2.5">
                  <div className="flex items-center gap-1.5">
                    <StatusDot status={req.complianceStatus as ComplianceStatus} />
                    <span className="capitalize">{req.complianceStatus === 'na' ? 'N/A' : req.complianceStatus}</span>
                  </div>
                </td>
                <td className={cn('px-3 py-2.5 font-medium', confColor(req.confidenceScore))}>
                  {req.confidenceScore !== null ? `${req.confidenceScore}%` : '0%'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>

      {/* Status bar */}
      <div className="flex items-center justify-between mt-3 px-1">
        <div className="flex items-center gap-2 text-[10px] text-success-600">
          <div className="w-1.5 h-1.5 rounded-full bg-success-400 animate-pulse" />
          Analysis Synchronized · Detected requirements: {MOCK_REQUIREMENTS.length}
        </div>
        <span className="text-[10px] text-[var(--text-tertiary)]">Compute Engine v4.2.0-stable</span>
      </div>
    </div>
  )
}