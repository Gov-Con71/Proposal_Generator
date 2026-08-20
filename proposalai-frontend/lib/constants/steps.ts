import type { Step } from '@/components/ui/card'

/** The new-proposal flow, defined once.
 *
 *  Each page used to hardcode its own copy of this array, and they had already
 *  drifted: `new` and `analyze` called step 3 "Outline" while `process` and
 *  `review` called it "Process", so the indicator silently renamed a step as
 *  the user walked through it. Deriving every page's indicator from one list
 *  makes that class of drift impossible. */
export const PROPOSAL_STEP_IDS = [
  'upload',
  'evidence',
  'analyze',
  'process',
  'review',
] as const

export type ProposalStepId = (typeof PROPOSAL_STEP_IDS)[number]

const LABELS: Record<ProposalStepId, string> = {
  upload: 'Upload RFP',
  evidence: 'Documents',
  analyze: 'Analyze',
  process: 'Process',
  review: 'Review',
}

/** Builds the indicator for a page: everything before `current` is done,
 *  everything after is pending. */
export function PROPOSAL_STEPS(current: ProposalStepId): Step[] {
  const currentIndex = PROPOSAL_STEP_IDS.indexOf(current)
  return PROPOSAL_STEP_IDS.map((id, i) => ({
    label: LABELS[id],
    status: i < currentIndex ? 'done' : i === currentIndex ? 'active' : 'pending',
  }))
}
