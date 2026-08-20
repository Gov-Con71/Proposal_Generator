'use client'
import { use } from 'react'
import { useRouter } from 'next/navigation'
import { ArrowRight, ArrowLeft, Info } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, StepIndicator } from '@/components/ui/card'
import { EmptyState } from '@/components/ui/state'
import { EvidenceUploader } from '@/components/history/evidence-uploader'
import { PROPOSAL_STEPS } from '@/lib/constants/steps'

/** Step 2 of the new-proposal flow: attach past work relevant to THIS bid.
 *
 *  Optional by design. A first-time user has nothing to attach yet, and plenty
 *  of solicitations don't turn on past performance at all — so the primary
 *  action always advances, and the upload is an opportunity rather than a gate.
 *
 *  Documents attached here are scoped to this proposal and deleted with it.
 *  The drafting agent prefers them over the long-term library, which only
 *  fills the gaps they leave. */
export default function EvidencePage({
  searchParams,
}: {
  searchParams: Promise<{ proposal?: string }>
}) {
  const router = useRouter()
  const { proposal } = use(searchParams)

  if (!proposal) {
    return (
      <div className="min-h-[calc(100vh-44px)] bg-[var(--bg-secondary)] flex items-center justify-center px-4">
        <Card className="w-full max-w-lg">
          <EmptyState
            title="No proposal to attach documents to"
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

  return (
    <div className="min-h-[calc(100vh-44px)] bg-[var(--bg-secondary)] flex flex-col items-center pt-12 px-4 pb-16">
      <div className="w-full max-w-2xl">
        <StepIndicator steps={PROPOSAL_STEPS('evidence')} className="mb-8" />

        <div className="mb-5">
          <h1 className="text-lg font-medium mb-1">Supporting documents</h1>
          <p className="text-xs text-[var(--text-secondary)]">
            Add past work relevant to <em>this</em> solicitation. Drafts will cite it before
            anything in your permanent library.
          </p>
        </div>

        <div className="flex items-start gap-2 mb-4 px-3 py-2.5 rounded-lg bg-primary-50">
          <Info className="w-3.5 h-3.5 text-primary-600 shrink-0 mt-0.5" />
          <p className="text-xs text-primary-800">
            Optional — you can skip this and add documents later. Anything you attach here belongs
            to this proposal only, and is removed if you delete it. For evidence you want on every
            bid, use the Past Performance library instead.
          </p>
        </div>

        <EvidenceUploader
          proposalId={proposal}
          emptyTitle="No documents attached yet"
          emptyMessage="Drop in prior proposals, CPARS reports, capability statements or project summaries relevant to this solicitation."
        />

        <div className="flex justify-between mt-6">
          <Button
            variant="default"
            icon={<ArrowLeft className="w-3.5 h-3.5" />}
            onClick={() => router.push('/proposals/new')}
          >
            Back
          </Button>
          <Button
            variant="primary"
            icon={<ArrowRight className="w-3.5 h-3.5" />}
            iconPosition="right"
            // Exactly where "Continue to Analysis" went before this step was
            // inserted. (/proposals/new/analyze is a separate, orphaned
            // profile-prefill page that nothing has ever linked to.)
            onClick={() => router.push(`/proposals/new/process?proposal=${proposal}`)}
          >
            Continue to Analysis
          </Button>
        </div>
      </div>
    </div>
  )
}
