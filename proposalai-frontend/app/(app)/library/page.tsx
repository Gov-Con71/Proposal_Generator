'use client'
import { Info } from 'lucide-react'
import { EvidenceUploader } from '@/components/history/evidence-uploader'

/** The long-term past-performance library.
 *
 *  Tenant-wide and permanent: every bid can draw on it, and nothing here is
 *  tied to a proposal's lifetime. Distinct from Company Profile's structured
 *  past-performance list, which holds the *facts* a claim may cite (contract
 *  numbers, values, customers) and backs the anti-fabrication guardrail. This
 *  page holds the *documents* retrieval searches for supporting prose. */
export default function LibraryPage() {
  return (
    <div className="page-padding">
      <div className="max-w-3xl">
        <div className="mb-5">
          <h1 className="text-lg font-medium mb-1">Past Performance Library</h1>
          <p className="text-xs text-[var(--text-secondary)]">
            Reusable evidence across every bid. Drafts search this whenever a proposal&rsquo;s own
            supporting documents don&rsquo;t cover a section.
          </p>
        </div>

        <div className="flex items-start gap-2 mb-4 px-3 py-2.5 rounded-lg bg-[var(--bg-primary)] border border-[var(--border-subtle)]">
          <Info className="w-3.5 h-3.5 text-[var(--text-tertiary)] shrink-0 mt-0.5" />
          <p className="text-xs text-[var(--text-secondary)]">
            This is separate from the past performance list on your{' '}
            <span className="font-medium text-[var(--text-primary)]">Profile</span>. That holds the
            facts a draft is allowed to cite — contract numbers, values, customers — and is what
            blocks a fabricated figure. This holds the documents those claims are written from.
          </p>
        </div>

        <EvidenceUploader
          emptyTitle="Your library is empty"
          emptyMessage="Add prior proposals, CPARS reports, capability statements and project summaries. Until there's something here, drafts have no evidence to cite and sections come back flagged as ungrounded."
        />
      </div>
    </div>
  )
}
