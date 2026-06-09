import type {
  ProposalSummary, Proposal, Requirement, ProposalSection,
  Pipeline, CompanyProfile, IntegrityItem
} from '@/types'

// ─── Proposals ───────────────────────────────────────────────────────────────
export const MOCK_PROPOSALS: ProposalSummary[] = [
  {
    id: '1',
    title: 'Centrifugal Pump Overhaul',
    solicitationNumber: 'NSN 4320-01-481-4914',
    agency: 'US Coast Guard',
    dueDate: '2026-06-15',
    complianceScore: 92,
    status: 'in_progress',
    createdAt: '2026-05-20T09:00:00Z',
    updatedAt: '2026-06-02T14:32:00Z',
  },
  {
    id: '2',
    title: 'IT Support Services BPA',
    solicitationNumber: 'W52P1J-26-R-0042',
    agency: 'Dept of Army',
    dueDate: '2026-06-28',
    complianceScore: 78,
    status: 'review_needed',
    createdAt: '2026-05-25T10:00:00Z',
    updatedAt: '2026-06-01T11:00:00Z',
  },
  {
    id: '3',
    title: 'Environmental Remediation SOW',
    solicitationNumber: 'EP-W3-26-0018',
    agency: 'EPA',
    dueDate: '2026-07-03',
    complianceScore: 45,
    status: 'incomplete',
    createdAt: '2026-05-28T08:00:00Z',
    updatedAt: '2026-05-30T16:00:00Z',
  },
  {
    id: '4',
    title: 'Logistics Support Contract',
    solicitationNumber: 'FA8721-26-R-0009',
    agency: 'USAF',
    dueDate: '2026-05-10',
    complianceScore: 100,
    status: 'submitted',
    createdAt: '2026-04-01T09:00:00Z',
    updatedAt: '2026-05-09T17:00:00Z',
  },
  {
    id: '5',
    title: 'Facility Management Services',
    solicitationNumber: 'GS-06P-26-DT-C-0023',
    agency: 'GSA',
    dueDate: '2026-04-22',
    complianceScore: 100,
    status: 'submitted',
    createdAt: '2026-03-15T09:00:00Z',
    updatedAt: '2026-04-21T15:00:00Z',
  },
]

export const MOCK_PROPOSAL: Proposal = {
  id: '1',
  title: 'Centrifugal Pump Overhaul',
  solicitationNumber: 'NSN 4320-01-481-4914',
  agency: 'US Coast Guard',
  dueDate: '2026-06-15',
  complianceScore: 92,
  status: 'in_progress',
  contractType: 'Firm Fixed Price (FFP)',
  naicsCode: '811310',
  naicsDescription: 'Commercial & Industrial Machinery Repair',
  pricingModel: 'FFP',
  targetProfitMargin: 12,
  draftingLevel: 'technical',
  tone: 'Authoritative & Precise',
  pageLimit: 0,
  documentId: 'doc-001',
  totalRequirements: 34,
  addressedRequirements: 22,
  partialRequirements: 8,
  missingRequirements: 3,
  createdAt: '2026-05-20T09:00:00Z',
  updatedAt: '2026-06-02T14:32:00Z',
}

// ─── Requirements ─────────────────────────────────────────────────────────────
export const MOCK_REQUIREMENTS: Requirement[] = [
  { id: 'r1',  proposalId: '1', number: 1,  section: '§1',     text: 'Contractor shall inspect, estimate, and overhaul the cited pump per NSN and part number',        category: 'scope',            type: 'mandatory', complianceStatus: 'addressed', confidenceScore: 96, proposalSectionId: 's1', proposalSectionTitle: 'Executive Summary',  createdAt: '' },
  { id: 'r2',  proposalId: '1', number: 2,  section: '§3.1',   text: 'Submit detailed cost estimate to CO prior to any repair or material order',                       category: 'admin',            type: 'mandatory', complianceStatus: 'addressed', confidenceScore: 91, proposalSectionId: 's2', proposalSectionTitle: 'Management Approach', createdAt: '' },
  { id: 'r3',  proposalId: '1', number: 3,  section: '§3.2',   text: 'All replacement parts shall be new — no reclaimed or recycled parts permitted',                  category: 'technical',        type: 'mandatory', complianceStatus: 'addressed', confidenceScore: 99, proposalSectionId: 's3', proposalSectionTitle: 'Technical Approach', createdAt: '' },
  { id: 'r4',  proposalId: '1', number: 4,  section: '§3.2.3', text: 'Mandatory replacement: all bearings, shaft seal, threaded fasteners',                            category: 'technical',        type: 'mandatory', complianceStatus: 'addressed', confidenceScore: 98, proposalSectionId: 's3', proposalSectionTitle: 'Technical Approach', createdAt: '' },
  { id: 'r5',  proposalId: '1', number: 5,  section: '§3.3.1', text: 'Convert packing gland to mechanical seal — Chesterton P/N 442-17 SPK 678344',                   category: 'technical',        type: 'mandatory', complianceStatus: 'partial',   confidenceScore: 74, proposalSectionId: 's3', proposalSectionTitle: 'Technical Approach', createdAt: '' },
  { id: 'r6',  proposalId: '1', number: 6,  section: '§3.4',   text: 'Motor overhaul cost not to exceed 70% of replacement cost — else exchange motor',               category: 'technical',        type: 'mandatory', complianceStatus: 'addressed', confidenceScore: 88, proposalSectionId: 's3', proposalSectionTitle: 'Technical Approach', createdAt: '' },
  { id: 'r7',  proposalId: '1', number: 7,  section: '§3.5',   text: 'Primer coat: high build epoxy MIL-PRF-23236, 5–6 mils DFT; finish: red silicone alkyd',         category: 'technical',        type: 'mandatory', complianceStatus: 'partial',   confidenceScore: 81, proposalSectionId: 's3', proposalSectionTitle: 'Technical Approach', createdAt: '' },
  { id: 'r8',  proposalId: '1', number: 8,  section: '§3.6.2', text: 'Rotational test — shaft rotated 5–10 times, witnessed by QAR',                                  category: 'testing',          type: 'mandatory', complianceStatus: 'addressed', confidenceScore: 95, proposalSectionId: 's4', proposalSectionTitle: 'Testing Plan',       createdAt: '' },
  { id: 'r9',  proposalId: '1', number: 9,  section: '§3.6.3', text: 'Hydrostatic test at 150% max working pressure, 10 min, witnessed by QAR',                       category: 'testing',          type: 'mandatory', complianceStatus: 'addressed', confidenceScore: 97, proposalSectionId: 's4', proposalSectionTitle: 'Testing Plan',       createdAt: '' },
  { id: 'r10', proposalId: '1', number: 10, section: '§3.6.4', text: 'Performance test per HI 1.6, Type III Level B — pump must meet or exceed flow curve ±5%',       category: 'testing',          type: 'mandatory', complianceStatus: 'missing',   confidenceScore: null, proposalSectionId: null, proposalSectionTitle: null,            createdAt: '' },
  { id: 'r11', proposalId: '1', number: 11, section: '§3.6.5', text: 'Test report packed with unit and copy to QAR — include contractor name, contract #, model',     category: 'reporting',        type: 'mandatory', complianceStatus: 'missing',   confidenceScore: null, proposalSectionId: null, proposalSectionTitle: null,            createdAt: '' },
  { id: 'r12', proposalId: '1', number: 12, section: '§4.3',   text: '7-day advance notice for QAR inspections within CONUS; 14 days outside CONUS',                  category: 'quality_assurance',type: 'mandatory', complianceStatus: 'partial',   confidenceScore: 70, proposalSectionId: 's5', proposalSectionTitle: 'Quality Plan',       createdAt: '' },
  { id: 'r13', proposalId: '1', number: 13, section: '§5',     text: 'Preservation: 8-mil poly bag, 32oz desiccant, rust inhibitor per MIL-PRF-81309F type 2',        category: 'packaging',        type: 'mandatory', complianceStatus: 'partial',   confidenceScore: 78, proposalSectionId: 's6', proposalSectionTitle: 'Packaging Plan',     createdAt: '' },
  { id: 'r14', proposalId: '1', number: 14, section: '§5.3',   text: 'Shipping container stenciled black enamel, 3/4" min height, on white background, two sides',   category: 'marking',          type: 'mandatory', complianceStatus: 'missing',   confidenceScore: null, proposalSectionId: null, proposalSectionTitle: null,            createdAt: '' },
]

// ─── Sections ─────────────────────────────────────────────────────────────────
export const MOCK_SECTIONS: ProposalSection[] = [
  {
    id: 's1',
    proposalId: '1',
    title: 'Executive Summary',
    content: `Acro Inc. (CAGE: 4G7B2) proposes to provide comprehensive overhaul services for one (1) Crane Deming Centrifugal Pump Unit, NSN 4320-01-481-4914, Part Number 3186-305-19999VA70E4X3X9.5-AB/D-605974-79, in strict accordance with the requirements set forth in the solicitation and applicable reference documents.\n\nAcro Inc. operates a fully equipped marine mechanical overhaul facility with hydrostatic test bench capability to 200 PSI, NIST-traceable calibrated instrumentation, and technicians experienced in SFLC overhaul standards. All work will be performed at our primary facility in accordance with Technical Publication 3901A, SWBS 521 Section A, and SFLC Standard Specification 3020.\n\nThe proposed overhaul encompasses complete disassembly, inspection, and reconditioning of the pump and drive motor to like-new condition, mandatory replacement of all bearings, seals, shaft seal, and threaded fasteners, hydrostatic and performance testing witnessed by the QAR, and preservation, packaging, and marking per MIL-STD-2073-1E.`,
    status: 'approved',
    wordCount: 142,
    aiConfidenceScore: 96,
    aiFlags: [],
    mappedRequirementIds: ['r1', 'r3', 'r8'],
    referenceTags: ['§1 Scope', '§3.1 Disassembly', '§3.4 Motor', 'Past Perf: HSCG84-24'],
    lastEditedAt: '2026-06-02T14:32:00Z',
    lastEditedBy: 'John Smith',
  },
  {
    id: 's3',
    proposalId: '1',
    title: 'Technical Approach',
    content: `Acro Inc. will perform a complete overhaul of the Crane Deming pump in strict accordance with Technical Publication 3901A, SWBS 521, Section A.\n\nAll replacement parts will be new — no reclaimed or recycled parts will be used. Mandatory replacements include all bearings, shaft seal, and threaded fasteners. Carbon steel fittings will be replaced with non-magnetic 300 series stainless steel.\n\nThe drive motor (75 HP, 440VAC, 3-phase, 3600 RPM) will be reconditioned to like-new condition with complete disassembly, cleaning, and inspection. Winding resistance will be inspected per SFLC Standard Specification 3020.`,
    status: 'needs_review',
    wordCount: 98,
    aiConfidenceScore: 88,
    aiFlags: [
      { id: 'f1', message: 'Section references Chesterton P/N 442-17 SPK 678344 — confirm part availability before submission', severity: 'warning' },
      { id: 'f2', message: 'Paint specification (MIL-PRF-23236) referenced but DFT thickness not explicitly stated in draft', severity: 'warning' },
    ],
    mappedRequirementIds: ['r3', 'r4', 'r5', 'r6', 'r7'],
    referenceTags: ['§3.2 Parts', '§3.3.1 Seal', '§3.4 Motor', '§3.5 Paint'],
    lastEditedAt: '2026-06-01T10:00:00Z',
    lastEditedBy: 'John Smith',
  },
]

// ─── Pipeline ─────────────────────────────────────────────────────────────────
export const MOCK_PIPELINE: Pipeline = {
  proposalId: '1',
  status: 'running',
  overallProgress: 64,
  startedAt: '2026-06-02T14:00:00Z',
  statusMessage: 'Optimizing vector embeddings for better retrieval...',
  steps: [
    { id: 'p1', label: 'S3 Upload',             description: 'PUMP_Overhaul_RFP.pdf — 2.4 MB',                        status: 'completed', completedAt: '2026-06-02T14:00:10Z' },
    { id: 'p2', label: 'Parser',                description: 'Extracted 9 sections, 4 tables, 47 text blocks',        status: 'completed', completedAt: '2026-06-02T14:00:18Z' },
    { id: 'p3', label: 'Compliance Extraction', description: '34 requirements identified across 6 categories',        status: 'completed', completedAt: '2026-06-02T14:00:35Z' },
    { id: 'p4', label: 'RAG Retrieval',          description: 'Querying vector index for relevant context...',         status: 'running' },
    { id: 'p5', label: 'Draft Generation',       description: 'Waiting for RAG retrieval to complete',                status: 'pending' },
    { id: 'p6', label: 'Matrix Mapping',         description: 'Waiting...',                                           status: 'pending' },
  ],
}

// ─── Company profile ──────────────────────────────────────────────────────────
export const MOCK_PROFILE: CompanyProfile = {
  id: 'cp1',
  legalName: 'Acro Inc.',
  dunsNumber: '08-123-4567',
  ueiNumber: 'J7K9M2L4P1Q3',
  primaryAddress: '1200 Innovation Way, Suite 400, Arlington, VA 22202',
  cageCode: '4G7B2',
  naicsCode: '811310',
  naicsDescription: 'Commercial & Industrial Machinery Repair',
  cmmcLevel: 'Level 2 (Advanced)',
  socioEconomicStatus: ['Small Business', 'SDVOSB'],
  annualRevenue: 14200000,
  fringeRate: 32.5,
  overheadRate: 14.2,
  gaRate: 8.9,
  capabilitiesOverview: 'Certified pump overhaul and marine mechanical systems repair. Facility equipped with hydrostatic test bench, precision balancing equipment, and NIST-traceable calibrated instrumentation. Technicians with SFLC standard experience.',
  certifications: ['ISO 9001:2015', 'MIL-SPEC compliant'],
  securityClearance: 'Secret',
  pastPerformance: [
    { id: 'pp1', contractNumber: 'HSCG84-24-C-PMP01', agency: 'USCG',     value: 38500,  scope: 'Pump overhaul, similar NSN',    period: '2024' },
    { id: 'pp2', contractNumber: 'N00024-23-C-4421',  agency: 'US Navy',  value: 92000,  scope: 'Marine mechanical systems',     period: '2023' },
    { id: 'pp3', contractNumber: 'GS-35F-0511',       agency: 'GSA FAS',  value: 4200000, scope: 'Cloud Infrastructure',         period: '2022-2024' },
  ],
  updatedAt: '2026-05-15T10:00:00Z',
}

// ─── Export integrity ─────────────────────────────────────────────────────────
export const MOCK_INTEGRITY_ITEMS: IntegrityItem[] = [
  { id: 'i1', label: 'Executive Summary & Vision',        status: 'verified' },
  { id: 'i2', label: 'Technical Approach',                status: 'verified' },
  { id: 'i3', label: 'Past Performance section',          status: 'verified' },
  { id: 'i4', label: 'Testing Plan — performance test',   status: 'review_required' },
  { id: 'i5', label: 'Packaging Plan — MIL-STD method',  status: 'review_required' },
  { id: 'i6', label: 'Marking Requirements',              status: 'missing' },
]