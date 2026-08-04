// ─── user.ts ─────────────────────────────────────────────────────────────────
export interface User {
  id: string
  email: string
  name: string
  role: 'admin' | 'analyst' | 'viewer'
  companyId: string
  avatarUrl?: string
  createdAt: string
}

export interface Session {
  user: User
  accessToken: string
  refreshToken: string
  expiresAt: string
}

// ─── profile.ts ──────────────────────────────────────────────────────────────
export interface PastPerformance {
  id: string
  contractNumber: string
  agency: string
  value: number
  scope: string
  period: string
}

export interface CompanyProfile {
  id: string
  legalName: string
  dunsNumber: string
  ueiNumber: string
  primaryAddress: string
  cageCode: string
  naicsCode: string
  naicsDescription: string
  cmmcLevel: string
  socioEconomicStatus: string[]
  annualRevenue: number
  fringeRate: number
  overheadRate: number
  gaRate: number
  capabilitiesOverview: string
  certifications: string[]
  securityClearance: string
  pastPerformance: PastPerformance[]
  updatedAt: string
}

// ─── proposal.ts ─────────────────────────────────────────────────────────────
export type ProposalStatus =
  | 'draft'
  | 'processing'
  | 'in_progress'
  | 'review_needed'
  | 'incomplete'
  | 'submitted'
  | 'archived'

export interface ProposalSummary {
  id: string
  title: string
  solicitationNumber: string
  agency: string
  dueDate: string
  complianceScore: number
  status: ProposalStatus
  createdAt: string
  updatedAt: string
}

export interface Proposal extends ProposalSummary {
  contractType: string
  naicsCode: string
  naicsDescription: string
  pricingModel: string
  targetProfitMargin: number
  draftingLevel: 'technical' | 'executive'
  tone: string
  pageLimit: number
  documentId: string
  totalRequirements: number
  addressedRequirements: number
  partialRequirements: number
  missingRequirements: number
}

// ─── requirement.ts ──────────────────────────────────────────────────────────
export type RequirementCategory =
  | 'scope'
  | 'technical'
  | 'testing'
  | 'quality_assurance'
  | 'packaging'
  | 'marking'
  | 'financial'
  | 'legal'
  | 'compliance'
  | 'personnel'
  | 'reporting'
  | 'security'
  | 'service_level'
  | 'admin'

export type RequirementType = 'mandatory' | 'optional' | 'technical'

export type ComplianceStatus = 'addressed' | 'partial' | 'missing' | 'na'

export interface Requirement {
  id: string
  /** The RFP this was extracted from (an rfp_id), matching Proposal.documentId. */
  documentId: string
  number: number
  section: string
  text: string
  category: RequirementCategory
  type: RequirementType
  complianceStatus: ComplianceStatus
  confidenceScore: number | null
  proposalSectionId: string | null
  proposalSectionTitle: string | null
  createdAt: string
}

export interface RequirementGroup {
  label: string
  requirements: Requirement[]
}

// ─── section.ts ──────────────────────────────────────────────────────────────
export type SectionStatus = 'draft' | 'approved' | 'needs_review' | 'empty'

export interface AIFlag {
  id: string
  message: string
  severity: 'warning' | 'error'
}

export interface ProposalSection {
  id: string
  /** The proposal that owns this section. Sections are per-proposal work
   *  product, not per-document: two proposals answering one RFP each keep
   *  their own drafts. */
  proposalId: string
  title: string
  content: string
  status: SectionStatus
  wordCount: number
  aiConfidenceScore: number
  aiFlags: AIFlag[]
  mappedRequirementIds: string[]
  referenceTags: string[]
  /** Compliance critic's unresolved feedback when the section is needs_review. */
  reviewNotes?: string | null
  lastEditedAt: string
  lastEditedBy: string
}

// ─── pipeline.ts ─────────────────────────────────────────────────────────────
export type PipelineStepStatus = 'pending' | 'running' | 'completed' | 'failed'

export interface PipelineStep {
  id: string
  label: string
  description: string
  status: PipelineStepStatus
  completedAt?: string
  meta?: string
}

export type PipelineStatus = 'idle' | 'running' | 'completed' | 'failed'

export interface Pipeline {
  proposalId: string
  status: PipelineStatus
  overallProgress: number
  steps: PipelineStep[]
  startedAt: string
  completedAt?: string
  statusMessage?: string
}

// ─── export.ts ───────────────────────────────────────────────────────────────
export type ExportFormat = 'pdf' | 'docx' | 'xlsx' | 'zip'

export interface ExportFormatOption {
  id: ExportFormat
  label: string
  description: string
  icon: string
}

export type IntegrityStatus = 'verified' | 'review_required' | 'missing'

export interface IntegrityItem {
  id: string
  label: string
  status: IntegrityStatus
}

export interface ExportJob {
  id: string
  proposalId: string
  format: ExportFormat
  status: 'pending' | 'generating' | 'ready' | 'failed'
  downloadUrl?: string
  createdAt: string
  expiresAt?: string
}

// ─── solicitation summary (documents.ts) ──────────────────────────────────────
// Returned by GET /documents/{rfpId}/summary. Unlike the rest of the API this
// endpoint is NOT camelCased — the backend returns the extracted summary verbatim
// in its citation schema — so these keys are snake_case on purpose, to mirror the
// wire format exactly. Every value carries a source_quote proving where it came
// from, and is null wherever the document was silent.
export interface Citation {
  value: string | null
  source_quote: string | null
}

export interface SolicitationSubmissionMethod {
  value: string | null
  description: string | null
  source_quote: string | null
}

export interface SolicitationPageLimit {
  volume: string
  limit: string
  source_quote: string
}

export interface SolicitationVolumeSection {
  name: string
  description: string
  source_quote: string
}

export interface SolicitationDeliverable {
  title: string
  description: string
  source_quote: string
}

export interface SolicitationSummary {
  administrative: {
    solicitation_number: Citation
    agency_or_organization: Citation
    title_of_opportunity: Citation
    naics_code: Citation
    set_aside_type: Citation
  }
  deadlines: {
    questions_due_date: Citation
    proposal_due_date: Citation
    period_of_performance: Citation
  }
  submission_requirements: {
    submission_method: SolicitationSubmissionMethod
    page_limits: SolicitationPageLimit[]
    required_volumes_or_sections: SolicitationVolumeSection[]
  }
  technical_core: {
    primary_objective: Citation
    key_deliverables: SolicitationDeliverable[]
  }
}