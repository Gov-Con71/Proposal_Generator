'use client'
import { useState } from 'react'
import { RefreshCw, ThumbsUp, ThumbsDown, AlertTriangle, ChevronDown, ChevronRight, Bold, Italic, List, Link2, Download } from 'lucide-react'
import Link from 'next/link'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { StatusDot } from '@/components/ui/card'
import { MOCK_REQUIREMENTS, MOCK_SECTIONS } from '@/lib/constants/mock-data'
import { cn } from '@/lib/utils/cn'
import type { Requirement, ComplianceStatus } from '@/types'

const GROUPS = [
  { label: 'I. Project Scope',      ids: ['r1', 'r2'] },
  { label: 'II. Technical Stack',   ids: ['r3', 'r4', 'r5', 'r6', 'r7'] },
  { label: 'III. Testing',          ids: ['r8', 'r9', 'r10', 'r11'] },
  { label: 'IV. Quality Assurance', ids: ['r12'] },
  { label: 'V. Packaging & Marking',ids: ['r13', 'r14'] },
]

export default function WorkspacePage({ params }: { params: { id: string } }) {
  const [selectedReqId, setSelectedReqId] = useState('r1')
  const [collapsed, setCollapsed] = useState<string[]>([])
  const [content, setContent] = useState(MOCK_SECTIONS[0]?.content || '')

  const selectedReq = MOCK_REQUIREMENTS.find((r) => r.id === selectedReqId)
  const section = MOCK_SECTIONS.find((s) => s.mappedRequirementIds.includes(selectedReqId)) || MOCK_SECTIONS[0]

  function toggleGroup(label: string) {
    setCollapsed((c) => c.includes(label) ? c.filter((x) => x !== label) : [...c, label])
  }

  function selectReq(req: Requirement) {
    setSelectedReqId(req.id)
    const s = MOCK_SECTIONS.find((sec) => sec.mappedRequirementIds.includes(req.id))
    if (s) setContent(s.content)
  }

  return (
    <div className="flex h-[calc(100vh-44px)]">
      {/* Left panel — requirements */}
      <div className="w-[280px] shrink-0 border-r border-[var(--border-subtle)] bg-[var(--bg-primary)] flex flex-col">
        <div className="flex items-center justify-between px-3 py-2.5 border-b border-[var(--border-subtle)]">
          <span className="text-xs font-medium">Grouped Requirements</span>
        </div>

        <div className="flex-1 overflow-y-auto scrollbar-thin">
          {GROUPS.map((group) => {
            const reqs = MOCK_REQUIREMENTS.filter((r) => group.ids.includes(r.id))
            const isCollapsed = collapsed.includes(group.label)
            return (
              <div key={group.label}>
                <button
                  onClick={() => toggleGroup(group.label)}
                  className="w-full flex items-center gap-1.5 px-3 py-2 text-xs font-medium text-primary-600 hover:bg-[var(--bg-secondary)] transition-colors"
                >
                  {isCollapsed ? <ChevronRight className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
                  {group.label}
                </button>
                {!isCollapsed && reqs.map((req) => (
                  <button
                    key={req.id}
                    onClick={() => selectReq(req)}
                    className={cn(
                      'w-full text-left px-4 py-2 border-b border-[var(--border-subtle)] transition-colors',
                      req.id === selectedReqId
                        ? 'bg-primary-50 border-l-2 border-l-primary-600'
                        : 'hover:bg-[var(--bg-secondary)]'
                    )}
                  >
                    <div className="flex items-center gap-2">
                      <StatusDot status={req.complianceStatus as ComplianceStatus} />
                      <span className="text-xs font-medium text-[var(--text-primary)] truncate">{req.text.slice(0, 40)}…</span>
                    </div>
                    <p className="text-[10px] text-[var(--text-tertiary)] mt-0.5 pl-3.5">{req.section} · Mandatory</p>
                  </button>
                ))}
              </div>
            )
          })}
        </div>

        <div className="p-3 border-t border-[var(--border-subtle)]">
          <Button variant="default" size="sm" className="w-full">Add Requirement</Button>
        </div>
      </div>

      {/* Right panel — editor */}
      <div className="flex-1 flex flex-col bg-[var(--bg-primary)] overflow-hidden">
        {/* Toolbar */}
        <div className="flex items-center gap-2 px-4 py-2.5 border-b border-[var(--border-subtle)] shrink-0">
          <Button variant="ghost" size="sm" icon={<RefreshCw className="w-3.5 h-3.5" />}>Regenerate Section</Button>
          <div className="w-px h-4 bg-[var(--border-default)]" />
          <Button variant="ghost" size="sm" icon={<ThumbsUp className="w-3.5 h-3.5" />}>AI Feedback</Button>
          <div className="ml-auto flex items-center gap-2">
            <div className="flex items-center gap-1">
              <div className="w-5 h-5 rounded-full bg-primary-100 flex items-center justify-center text-[9px] text-primary-800 font-medium">JS</div>
              <div className="w-5 h-5 rounded-full bg-success-50 flex items-center justify-center text-[9px] text-success-600 font-medium -ml-1.5">+2</div>
            </div>
            <span className="text-xs text-[var(--text-tertiary)]">Last edited 2m ago</span>
          </div>
        </div>

        <div className="flex-1 overflow-y-auto p-5 scrollbar-thin">
          {/* AI compliance flag */}
          {section?.aiFlags && section.aiFlags.length > 0 && (
            <div className="flex items-start gap-3 px-4 py-3 bg-[var(--warning-bg)] border border-[var(--warning-border)] rounded-lg mb-4">
              <AlertTriangle className="w-4 h-4 text-warning-400 shrink-0 mt-0.5" />
              <div className="flex-1">
                <p className="text-xs font-medium text-[var(--warning-text)] uppercase tracking-wider mb-1">AI Compliance Flag</p>
                {section.aiFlags.map((f) => (
                  <p key={f.id} className="text-xs text-[var(--warning-text)]">{f.message}</p>
                ))}
              </div>
              <Button variant="ghost" size="sm" className="text-warning-600 hover:text-warning-800 shrink-0">Fix Now</Button>
            </div>
          )}

          {/* Reference tags */}
          {section?.referenceTags && (
            <div className="flex flex-wrap gap-1.5 mb-4">
              {section.referenceTags.map((tag) => (
                <span key={tag} className="inline-flex items-center gap-1 px-2 py-0.5 bg-primary-50 border border-primary-100 rounded text-xs text-primary-800">
                  {tag} <button className="hover:text-danger-600"><X className="w-2.5 h-2.5" /></button>
                </span>
              ))}
              <button className="px-2 py-0.5 border border-dashed border-[var(--border-default)] rounded text-xs text-[var(--text-tertiary)] hover:border-primary-600 hover:text-primary-600 transition-colors">
                + Add Reference
              </button>
            </div>
          )}

          {/* Section title */}
          <h2 className="text-lg font-medium mb-4">
            {selectedReq ? `${section?.title || 'Section'}` : 'Select a requirement'}
          </h2>

          {/* Editable content */}
          <div
            contentEditable
            suppressContentEditableWarning
            onInput={(e) => setContent(e.currentTarget.textContent || '')}
            className="text-sm text-[var(--text-primary)] leading-relaxed min-h-[200px] focus:outline-none border border-transparent focus:border-[var(--border-default)] rounded-lg p-3 -mx-3 transition-colors whitespace-pre-wrap"
          >
            {content}
          </div>
        </div>

        {/* Bottom toolbar */}
        <div className="flex items-center gap-2 px-4 py-2.5 border-t border-[var(--border-subtle)] shrink-0">
          <div className="flex items-center gap-1">
            {[Bold, Italic, List, Link2].map((Icon, i) => (
              <button key={i} className="w-7 h-7 flex items-center justify-center rounded hover:bg-[var(--bg-secondary)] text-[var(--text-secondary)] transition-colors">
                <Icon className="w-3.5 h-3.5" />
              </button>
            ))}
          </div>
          <div className="ml-auto flex items-center gap-4 text-xs text-[var(--text-tertiary)]">
            <span>Words: {content.trim().split(/\s+/).filter(Boolean).length}</span>
            <span>AI Confidence: {section?.aiConfidenceScore ?? '—'}%</span>
          </div>
          <div className="flex items-center gap-2 ml-4">
            <Button variant="default" size="sm">← Previous Section</Button>
            <Button variant="default" size="sm">Save Draft</Button>
            <Button variant="primary" size="sm" icon={<ArrowRight className="w-3.5 h-3.5" />} iconPosition="right">
              Approve &amp; Next
            </Button>
          </div>
        </div>
      </div>
    </div>
  )
}

function X({ className }: { className?: string }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
    </svg>
  )
}

function ArrowRight({ className }: { className?: string }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M13 7l5 5m0 0l-5 5m5-5H6" />
    </svg>
  )
}