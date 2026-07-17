'use client'
import Link from 'next/link'
import { ExternalLink, Filter, Download, FilePlus2 } from 'lucide-react'
import { useState } from 'react'
import { Card } from '@/components/ui/card'
import { ProposalStatusBadge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { ProgressBar, Skeleton } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { EmptyState, ErrorState, TableSkeleton } from '@/components/ui/state'
import { useProposals } from '@/lib/hooks'
import { formatDate } from '@/lib/utils/format'

export default function DashboardPage() {
  const [search, setSearch] = useState('')
  const { data: proposals = [], isLoading, isError, error, refetch } = useProposals()

  const filtered = proposals.filter(
    (p) =>
      p.title.toLowerCase().includes(search.toLowerCase()) ||
      p.solicitationNumber.toLowerCase().includes(search.toLowerCase()) ||
      p.agency.toLowerCase().includes(search.toLowerCase())
  )

  const total      = proposals.length
  const inProgress = proposals.filter((p) => p.status === 'in_progress' || p.status === 'review_needed' || p.status === 'incomplete').length
  const submitted  = proposals.filter((p) => p.status === 'submitted').length
  const avgCompliance = total ? Math.round(proposals.reduce((a, p) => a + p.complianceScore, 0) / total) : 0

  return (
    <div className="page-padding">
      {/* Header */}
      <div className="flex items-start justify-between mb-5">
        <div>
          <h1 className="text-lg font-medium text-[var(--text-primary)]">Organization Dashboard</h1>
          <p className="text-xs text-[var(--text-secondary)] mt-0.5">
            Real-time oversight of ongoing federal acquisition responses and compliance scores.
          </p>
        </div>
      </div>

      {/* Metric cards — every value is derived from the loaded proposals. */}
      <div className="grid grid-cols-4 gap-3 mb-5">
        {[
          { label: 'TOTAL PROPOSALS', value: total,               color: '' },
          { label: 'IN PROGRESS',     value: inProgress,          color: 'text-primary-600' },
          { label: 'SUBMITTED',       value: submitted,           color: 'text-success-600' },
          { label: 'AVG COMPLIANCE %',value: `${avgCompliance}%`, color: 'text-warning-400' },
        ].map((m) => (
          <Card key={m.label} className="p-4">
            <p className="text-[10px] font-medium text-[var(--text-tertiary)] tracking-wider uppercase mb-2">{m.label}</p>
            {isLoading
              ? <Skeleton height={28} width={48} />
              : <p className={`text-2xl font-medium ${m.color || 'text-[var(--text-primary)]'}`}>{m.value}</p>}
          </Card>
        ))}
      </div>

      {/* Search + actions */}
      <div className="flex items-center gap-3 mb-3">
        <div className="w-72">
          <Input
            placeholder="Search solicitation ID or title..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
        <div className="ml-auto flex gap-2">
          <Button variant="default" size="sm" icon={<Filter className="w-3.5 h-3.5" />}>Filter</Button>
          <Button variant="default" size="sm" icon={<Download className="w-3.5 h-3.5" />}>Export</Button>
        </div>
      </div>

      {/* Proposals table */}
      <Card padding="none" className="overflow-hidden mb-4">
        <table className="w-full text-sm border-collapse">
          <thead>
            <tr className="bg-[var(--bg-secondary)]">
              {['SOLICITATION TITLE', 'AGENCY', 'DUE DATE', 'COMPLIANCE', 'STATUS', 'ACTION'].map((h) => (
                <th key={h} className="text-left text-[10px] font-medium text-[var(--text-tertiary)] tracking-wider px-4 py-2.5 border-b border-[var(--border-subtle)]">
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {isLoading && <TableSkeleton cols={6} />}
            {!isLoading && filtered.map((p) => (
              <tr key={p.id} className="border-b border-[var(--border-subtle)] hover:bg-[var(--bg-secondary)] transition-colors">
                <td className="px-4 py-3">
                  <Link href={`/proposals/${p.id}/workspace`} className="text-primary-600 hover:text-primary-800 font-medium text-xs transition-colors">
                    {p.solicitationNumber}
                  </Link>
                  <p className="text-[10px] text-[var(--text-tertiary)] mt-0.5">{p.title}</p>
                </td>
                <td className="px-4 py-3 text-xs text-[var(--text-secondary)]">{p.agency}</td>
                <td className="px-4 py-3 text-xs text-[var(--text-secondary)]">{formatDate(p.dueDate)}</td>
                <td className="px-4 py-3">
                  <div className="flex items-center gap-2 w-32">
                    <ProgressBar value={p.complianceScore} colorByValue showLabel />
                  </div>
                </td>
                <td className="px-4 py-3">
                  <ProposalStatusBadge status={p.status} />
                </td>
                <td className="px-4 py-3">
                  <Link href={`/proposals/${p.id}/workspace`}>
                    <ExternalLink className="w-3.5 h-3.5 text-[var(--text-tertiary)] hover:text-primary-600 transition-colors" />
                  </Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>

        {isError && <ErrorState title="Could not load proposals" error={error} onRetry={() => refetch()} />}

        {!isLoading && !isError && proposals.length === 0 && (
          <EmptyState
            title="No proposals yet"
            message="Upload an RFP and ProposalAI will extract its requirements and start a compliance matrix."
            icon={<FilePlus2 className="w-5 h-5 text-[var(--text-tertiary)]" />}
            action={
              <Link href="/proposals/new">
                <Button variant="primary" size="sm">Upload an RFP</Button>
              </Link>
            }
          />
        )}

        {!isLoading && !isError && proposals.length > 0 && filtered.length === 0 && (
          <EmptyState
            title="No matching proposals"
            message={`Nothing matches "${search}". Try a different solicitation number, title, or agency.`}
          />
        )}
      </Card>
    </div>
  )
}