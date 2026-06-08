// ─── nav.ts ───────────────────────────────────────────────────────────────────
export const NAV_GROUPS = [
  {
    label: 'PROPOSALS',
    items: [
      { href: '/dashboard',    label: 'Current',     icon: 'LayoutDashboard' },
      { href: '/proposals',    label: 'Archive',     icon: 'Archive' },
      { href: '/templates',    label: 'Templates',   icon: 'FileText' },
      { href: '/calculators',  label: 'Calculators', icon: 'Calculator' },
    ],
  },
  {
    label: 'ACCOUNT',
    items: [
      { href: '/profile',  label: 'Profile',  icon: 'Building2' },
      { href: '/security', label: 'Security', icon: 'Shield' },
    ],
  },
]

// ─── pipeline-steps.ts ────────────────────────────────────────────────────────
export const PIPELINE_STEP_LABELS: Record<string, string> = {
  s3_upload:             'S3 Upload',
  parser:                'Parser',
  compliance_extraction: 'Compliance Extraction',
  rag_retrieval:         'RAG Retrieval',
  draft_generation:      'Draft Generation',
  matrix_mapping:        'Matrix Mapping',
}

// ─── requirement-types.ts ─────────────────────────────────────────────────────
export const REQUIREMENT_CATEGORIES = [
  { value: 'scope',             label: 'Scope' },
  { value: 'technical',         label: 'Technical' },
  { value: 'testing',           label: 'Testing' },
  { value: 'quality_assurance', label: 'Quality Assurance' },
  { value: 'packaging',         label: 'Packaging' },
  { value: 'marking',           label: 'Marking' },
  { value: 'financial',         label: 'Financial' },
  { value: 'legal',             label: 'Legal' },
  { value: 'compliance',        label: 'Compliance' },
  { value: 'personnel',         label: 'Personnel' },
  { value: 'reporting',         label: 'Reporting' },
  { value: 'security',          label: 'Security' },
  { value: 'service_level',     label: 'Service Level' },
  { value: 'admin',             label: 'Admin' },
]

export const COMPLIANCE_STATUSES = [
  { value: 'addressed', label: 'Addressed', color: '#639922' },
  { value: 'partial',   label: 'Partial',   color: '#BA7517' },
  { value: 'missing',   label: 'Missing',   color: '#E24B4A' },
  { value: 'na',        label: 'N/A',       color: '#888780' },
]

// ─── export-formats.ts ────────────────────────────────────────────────────────
export const EXPORT_FORMATS = [
  { id: 'pdf',  label: 'PDF',   description: 'Universal',  icon: 'FileText' },
  { id: 'docx', label: 'Word',  description: 'Editable',   icon: 'FileText' },
  { id: 'xlsx', label: 'Excel', description: 'Data Only',  icon: 'FileSpreadsheet' },
  { id: 'zip',  label: 'ZIP',   description: 'All Files',  icon: 'Archive' },
]