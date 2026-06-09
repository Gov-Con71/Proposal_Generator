'use client'
import { create } from 'zustand'
import type { Proposal, Requirement, ProposalSection } from '@/types'

interface ProposalState {
  activeProposal: Proposal | null
  selectedRequirement: Requirement | null
  activeSection: ProposalSection | null

  setActiveProposal: (proposal: Proposal | null) => void
  setSelectedRequirement: (requirement: Requirement | null) => void
  setActiveSection: (section: ProposalSection | null) => void
  reset: () => void
}

export const useProposalStore = create<ProposalState>((set) => ({
  activeProposal: null,
  selectedRequirement: null,
  activeSection: null,

  setActiveProposal: (proposal) => set({ activeProposal: proposal }),
  setSelectedRequirement: (requirement) => set({ selectedRequirement: requirement }),
  setActiveSection: (section) => set({ activeSection: section }),
  reset: () => set({
    activeProposal: null,
    selectedRequirement: null,
    activeSection: null,
  }),
}))