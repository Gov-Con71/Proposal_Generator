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
  proposalId: string
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
  proposalId: string
  title: string
  content: string
  status: SectionStatus
  wordCount: number
  aiConfidenceScore: number
  aiFlags: AIFlag[]
  mappedRequirementIds: string[]
  referenceTags: string[]
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