'use client'
import { useState, use } from 'react'
import { RefreshCw, ThumbsUp, Bold, Italic, List, Link2, Download, ChevronDown, ChevronRight, AlertTriangle } from 'lucide-react'
import Link from 'next/link'
import { Button } from '@/components/ui/button'
import { StatusDot } from '@/components/ui/card'
import { MOCK_REQUIREMENTS, MOCK_SECTIONS } from '@/lib/constants/mock-data'
import { cn } from '@/lib/utils/cn'
import type { Requirement, ComplianceStatus } from '@/types'

const GROUPS = [
  { label: 'I. Project Scope',       ids: ['r1', 'r2'] },
  { label: 'II. Technical Stack',    ids: ['r3', 'r4', 'r5', 'r6', 'r7'] },
  { label: 'III. Testing',           ids: ['r8', 'r9', 'r10', 'r11'] },
  { label: 'IV. Quality Assurance',  ids: ['r12'] },
  { label: 'V. Packaging & Marking', ids: ['r13', 'r14'] },
]

export default function WorkspacePage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params)
  const [selectedReqId, setSelectedReqId] = useState('r1')
  const [collapsed, setCollapsed] = useState<string[]>([])
  const [content, setContent] = useState(MOCK_SECTIONS[0]?.content || '')

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
    <div className="flex" style={{ height: 'calc(100vh - 88px)' }}>
      {/* Left panel */}
      <div className="w-72 shrink-0 border-r border-neutral-100 bg-white flex flex-col">
        <div className="flex items-center justify-between px-3 py-2.5 border-b border-neutral-100">
          <span className="text-xs font-medium text-neutral-800">Grouped Requirements</span>
        </div>
        <div className="flex-1 overflow-y-auto">
          {GROUPS.map((group) => {
            const reqs = MOCK_REQUIREMENTS.filter((r) => group.ids.includes(r.id))
            const isCollapsed = collapsed.includes(group.label)
            return (
              <div key={group.label}>
                <button
                  onClick={() => toggleGroup(group.label)}
                  className="w-full flex items-center gap-1.5 px-3 py-2 text-xs font-medium text-primary-600 hover:bg-neutral-50 transition-colors"
                >
                  {isCollapsed ? <ChevronRight className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
                  {group.label}
                </button>
                {!isCollapsed && reqs.map((req) => (
                  <button
                    key={req.id}
                    onClick={() => selectReq(req)}
                    className={cn(
                      'w-full text-left px-4 py-2 border-b border-neutral-50 transition-colors',
                      req.id === selectedReqId
                        ? 'bg-primary-50 border-l-2 border-l-primary-600'
                        : 'hover:bg-neutral-50'
                    )}
                  >
                    <div className="flex items-center gap-2">
                      <StatusDot status={req.complianceStatus as ComplianceStatus} />
                      <span className="text-xs font-medium text-neutral-800 truncate">{req.text.slice(0, 40)}…</span>
                    </div>
                    <p className="text-[10px] text-neutral-400 mt-0.5 pl-3.5">{req.section} · Mandatory</p>
                  </button>
                ))}
              </div>
            )
          })}
        </div>
        <div className="p-3 border-t border-neutral-100">
          <Button variant="default" size="sm" className="w-full">Add Requirement</Button>
        </div>
      </div>

      {/* Right panel */}
      <div className="flex-1 flex flex-col bg-white overflow-hidden">
        <div className="flex items-center gap-2 px-4 py-2.5 border-b border-neutral-100 shrink-0">
          <Button variant="ghost" size="sm" icon={<RefreshCw className="w-3.5 h-3.5" />}>Regenerate Section</Button>
          <div className="w-px h-4 bg-neutral-200" />
          <Button variant="ghost" size="sm" icon={<ThumbsUp className="w-3.5 h-3.5" />}>AI Feedback</Button>
          <div className="ml-auto">
            <span className="text-xs text-neutral-400">Last edited 2m ago</span>
          </div>
        </div>

        <div className="flex-1 overflow-y-auto p-5">
          {section?.aiFlags && section.aiFlags.length > 0 && (
            <div className="flex items-start gap-3 px-4 py-3 bg-warning-50 border border-warning-100 rounded-lg mb-4">
              <AlertTriangle className="w-4 h-4 text-warning-400 shrink-0 mt-0.5" />
              <div className="flex-1">
                <p className="text-xs font-medium text-warning-600 uppercase tracking-wider mb-1">AI Compliance Flag</p>
                {section.aiFlags.map((f) => (
                  <p key={f.id} className="text-xs text-warning-600">{f.message}</p>
                ))}
              </div>
              <Button variant="ghost" size="sm" className="text-warning-600 shrink-0">Fix Now</Button>
            </div>
          )}

          {section?.referenceTags && (
            <div className="flex flex-wrap gap-1.5 mb-4">
              {section.referenceTags.map((tag) => (
                <span key={tag} className="inline-flex items-center px-2 py-0.5 bg-primary-50 border border-primary-100 rounded text-xs text-primary-800">
                  {tag}
                </span>
              ))}
            </div>
          )}

          <h2 className="text-lg font-medium mb-4 text-neutral-800">{section?.title || 'Select a requirement'}</h2>

          <div
            contentEditable
            suppressContentEditableWarning
            onInput={(e) => setContent(e.currentTarget.textContent || '')}
            className="text-sm text-neutral-700 leading-relaxed min-h-48 focus:outline-none whitespace-pre-wrap"
          >
            {content}
          </div>
        </div>

        <div className="flex items-center gap-2 px-4 py-2.5 border-t border-neutral-100 shrink-0">
          <div className="flex items-center gap-1">
            {[Bold, Italic, List, Link2].map((Icon, i) => (
              <button key={i} className="w-7 h-7 flex items-center justify-center rounded hover:bg-neutral-100 text-neutral-500 transition-colors">
                <Icon className="w-3.5 h-3.5" />
              </button>
            ))}
          </div>
          <div className="ml-auto flex items-center gap-4 text-xs text-neutral-400">
            <span>Words: {content.trim().split(/\s+/).filter(Boolean).length}</span>
            <span>AI Confidence: {section?.aiConfidenceScore ?? '—'}%</span>
          </div>
          <div className="flex items-center gap-2 ml-4">
            <Button variant="default" size="sm">← Previous</Button>
            <Button variant="default" size="sm">Save Draft</Button>
            <Button variant="primary" size="sm">Approve & Next →</Button>
          </div>
        </div>
      </div>
    </div>
  )
}