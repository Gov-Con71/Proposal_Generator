'use client'
import Link from 'next/link'
import { ExternalLink } from 'lucide-react'
import { Card } from '@/components/ui/card'
import { ProposalStatusBadge } from '@/components/ui/badge'
import { ProgressBar } from '@/components/ui/card'
import { useProposals } from '@/lib/hooks'
import { formatDate } from '@/lib/utils/format'

export default function ProposalsPage() {
  const { data: proposals = [] } = useProposals()
  const archived = proposals.filter((p) => p.status === 'submitted')

  return (
    <div className="page-padding">
      <div className="mb-5">
        <h1 className="text-lg font-medium">Archive</h1>
        <p className="text-xs text-[var(--text-secondary)] mt-0.5">All submitted proposals</p>
      </div>
      <Card padding="none" className="overflow-hidden">
        <table className="w-full text-sm border-collapse">
          <thead>
            <tr className="bg-[var(--bg-secondary)]">
              {['SOLICITATION', 'AGENCY', 'SUBMITTED', 'COMPLIANCE', 'STATUS', ''].map((h) => (
                <th key={h} className="text-left text-[10px] font-medium text-[var(--text-tertiary)] tracking-wider px-4 py-2.5 border-b border-[var(--border-subtle)]">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {archived.map((p) => (
              <tr key={p.id} className="border-b border-[var(--border-subtle)] last:border-0 hover:bg-[var(--bg-secondary)] transition-colors">
                <td className="px-4 py-3">
                  <p className="text-xs font-medium text-[var(--text-primary)]">{p.title}</p>
                  <p className="text-[10px] text-[var(--text-tertiary)]">{p.solicitationNumber}</p>
                </td>
                <td className="px-4 py-3 text-xs text-[var(--text-secondary)]">{p.agency}</td>
                <td className="px-4 py-3 text-xs text-[var(--text-secondary)]">{formatDate(p.updatedAt)}</td>
                <td className="px-4 py-3"><ProgressBar value={p.complianceScore} colorByValue showLabel className="w-28" /></td>
                <td className="px-4 py-3"><ProposalStatusBadge status={p.status} /></td>
                <td className="px-4 py-3">
                  <Link href={`/proposals/${p.id}/workspace`}>
                    <ExternalLink className="w-3.5 h-3.5 text-[var(--text-tertiary)] hover:text-primary-600 transition-colors" />
                  </Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
    </div>
  )
}