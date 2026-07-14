'use client'
import { useMemo, useState, use } from 'react'
import { RefreshCw, Loader2, Bold, Italic, List, Link2, ChevronDown, ChevronRight } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { StatusDot } from '@/components/ui/card'
import { useRequirements, useGenerateSection, useSaveSection } from '@/lib/hooks'
import { cn } from '@/lib/utils/cn'
import type { Requirement, ComplianceStatus } from '@/types'

function categoryLabel(cat: string) {
  return cat.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
}

export default function WorkspacePage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params)
  const { data: requirements = [] } = useRequirements(id)
  const generate = useGenerateSection(id)
  const saveSection = useSaveSection(id)

  const [selectedReqId, setSelectedReqId] = useState<string | null>(null)
  const [collapsed, setCollapsed] = useState<string[]>([])
  const [content, setContent] = useState('')
  const [sectionId, setSectionId] = useState<string | null>(null)

  const selectedReq = requirements.find((r) => r.id === selectedReqId) ?? requirements[0]

  // Group real requirements by their category (replaces hardcoded id groups).
  const groups = useMemo(() => {
    const m = new Map<string, Requirement[]>()
    for (const r of requirements) {
      const key = r.category || 'other'
      if (!m.has(key)) m.set(key, [])
      m.get(key)!.push(r)
    }
    return Array.from(m.entries())
  }, [requirements])

  function toggleGroup(label: string) {
    setCollapsed((c) => (c.includes(label) ? c.filter((x) => x !== label) : [...c, label]))
  }

  async function handleGenerate() {
    if (!selectedReq) return
    const section = await generate.mutateAsync(selectedReq.id)
    setSectionId(section.id)
    setContent(section.content)
  }

  async function handleSave() {
    if (sectionId) await saveSection.mutateAsync({ id: sectionId, content })
  }

  const wordCount = content.trim().split(/\s+/).filter(Boolean).length

  return (
    <div className="flex" style={{ height: 'calc(100vh - 88px)' }}>
      {/* Left panel — requirements grouped by category */}
      <div className="w-72 shrink-0 border-r border-neutral-100 bg-white flex flex-col">
        <div className="flex items-center justify-between px-3 py-2.5 border-b border-neutral-100">
          <span className="text-xs font-medium text-neutral-800">Grouped Requirements</span>
          <span className="text-[10px] text-neutral-400">{requirements.length}</span>
        </div>
        <div className="flex-1 overflow-y-auto">
          {groups.length === 0 && (
            <p className="px-4 py-6 text-xs text-neutral-400">No requirements yet — upload an RFP to extract them.</p>
          )}
          {groups.map(([category, reqs]) => {
            const isCollapsed = collapsed.includes(category)
            return (
              <div key={category}>
                <button
                  onClick={() => toggleGroup(category)}
                  className="w-full flex items-center gap-1.5 px-3 py-2 text-xs font-medium text-primary-600 hover:bg-neutral-50 transition-colors"
                >
                  {isCollapsed ? <ChevronRight className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
                  {categoryLabel(category)} <span className="text-neutral-400">({reqs.length})</span>
                </button>
                {!isCollapsed && reqs.map((req) => (
                  <button
                    key={req.id}
                    onClick={() => setSelectedReqId(req.id)}
                    className={cn(
                      'w-full text-left px-4 py-2 border-b border-neutral-50 transition-colors',
                      req.id === selectedReq?.id
                        ? 'bg-primary-50 border-l-2 border-l-primary-600'
                        : 'hover:bg-neutral-50'
                    )}
                  >
                    <div className="flex items-center gap-2">
                      <StatusDot status={req.complianceStatus as ComplianceStatus} />
                      <span className="text-xs font-medium text-neutral-800 truncate">{req.text.slice(0, 40)}…</span>
                    </div>
                    <p className="text-[10px] text-neutral-400 mt-0.5 pl-3.5">{req.section} · {req.type}</p>
                  </button>
                ))}
              </div>
            )
          })}
        </div>
      </div>

      {/* Right panel — draft canvas */}
      <div className="flex-1 flex flex-col bg-white overflow-hidden">
        <div className="flex items-center gap-2 px-4 py-2.5 border-b border-neutral-100 shrink-0">
          <Button
            variant="ghost"
            size="sm"
            icon={generate.isPending ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <RefreshCw className="w-3.5 h-3.5" />}
            disabled={!selectedReq || generate.isPending}
            onClick={handleGenerate}
          >
            {generate.isPending ? 'Generating…' : 'Generate with AI'}
          </Button>
          <div className="ml-auto">
            {generate.isError && <span className="text-xs text-danger-600">Generation failed</span>}
          </div>
        </div>

        <div className="flex-1 overflow-y-auto p-5">
          <h2 className="text-lg font-medium mb-4 text-neutral-800">
            {selectedReq ? `${selectedReq.section} — ${categoryLabel(selectedReq.category)}` : 'Select a requirement'}
          </h2>
          {selectedReq && (
            <p className="text-xs text-neutral-500 mb-4 p-3 bg-neutral-50 rounded-lg">{selectedReq.text}</p>
          )}

          <div
            key={sectionId ?? 'empty'}
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
            <span>Words: {wordCount}</span>
          </div>
          <div className="flex items-center gap-2 ml-4">
            <Button variant="default" size="sm" disabled={!sectionId || saveSection.isPending} onClick={handleSave}>
              {saveSection.isPending ? 'Saving…' : 'Save Draft'}
            </Button>
          </div>
        </div>
      </div>
    </div>
  )
}
