// ─── compliance.ts ────────────────────────────────────────────────────────────
import type { Requirement } from '@/types'

export function calcComplianceScore(requirements: Requirement[]): number {
  if (!requirements.length) return 0
  const mandatory = requirements.filter((r) => r.type === 'mandatory')
  if (!mandatory.length) return 0
  const addressed = mandatory.filter((r) => r.complianceStatus === 'addressed').length
  const partial   = mandatory.filter((r) => r.complianceStatus === 'partial').length
  return Math.round(((addressed + partial * 0.5) / mandatory.length) * 100)
}

export function groupRequirementsBySection(requirements: Requirement[]) {
  return requirements.reduce((acc, req) => {
    const key = req.section.split('.')[0]
    if (!acc[key]) acc[key] = []
    acc[key].push(req)
    return acc
  }, {} as Record<string, Requirement[]>)
}

// ─── file.ts ──────────────────────────────────────────────────────────────────
export function getFileExtension(filename: string): string {
  return filename.split('.').pop()?.toLowerCase() || ''
}

export function isAllowedFileType(file: File): boolean {
  const allowed = ['application/pdf', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document', 'text/plain']
  return allowed.includes(file.type)
}

export function getFileIcon(filename: string): 'pdf' | 'docx' | 'txt' | 'unknown' {
  const ext = getFileExtension(filename)
  if (ext === 'pdf')  return 'pdf'
  if (ext === 'docx') return 'docx'
  if (ext === 'txt')  return 'txt'
  return 'unknown'
}