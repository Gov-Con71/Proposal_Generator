'use client'
import { useMemo, useState, use } from 'react'
import { RefreshCw, Loader2, Sparkles, Bold, Italic, List, Link2, ChevronDown, ChevronRight } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { StatusDot } from '@/components/ui/card'
import { ErrorState } from '@/components/ui/state'
import {
  useProposal,
  useRequirements,
  useGenerateSection,
  useGenerateDraft,
  useSaveSection,
  useSections,
  isValidId,
} from '@/lib/hooks'
import { cn } from '@/lib/utils/cn'
import type { Requirement, ComplianceStatus, ProposalSection } from '@/types'

function categoryLabel(cat: string) {
  return cat.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
}

function sectionStatusClass(status: string) {
  switch (status) {
    case 'approved': return 'bg-primary-50 text-primary-700'
    case 'needs_review': return 'bg-amber-50 text-amber-700'
    case 'empty': return 'bg-neutral-100 text-danger-600'
    default: return 'bg-neutral-100 text-neutral-500'
  }
}

export default function WorkspacePage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params)
  const { data: requirements = [], isLoading, isError, error, refetch } = useRequirements(id)
  const generate = useGenerateSection(id)
  const saveSection = useSaveSection(id)

  // Drafting is queued against this proposal (its sections are its own), but
  // progress is polled on the document behind it, whose id is documentId.
  const proposal = useProposal(id)
  const rfpId = proposal.data?.documentId ?? ''
  const draft = useGenerateDraft(rfpId, id)
  const { data: sections = [] } = useSections(id)

  const [selectedReqId, setSelectedReqId] = useState<string | null>(null)
  const [collapsed, setCollapsed] = useState<string[]>([])
  const [content, setContent] = useState('')
  const [sectionId, setSectionId] = useState<string | null>(null)
  // Metadata of the section currently open in the canvas (from a full-draft
  // section or a per-requirement generation), for the header badge + notes.
  const [openMeta, setOpenMeta] = useState<
    { title: string; status: string; reviewNotes?: string | null } | null
  >(null)

  function openSection(s: ProposalSection) {
    setSectionId(s.id)
    setContent(s.content)
    setOpenMeta({ title: s.title, status: s.status, reviewNotes: s.reviewNotes })
    setSelectedReqId(null)
  }

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
    setOpenMeta({ title: section.title, status: section.status, reviewNotes: section.reviewNotes })
  }

  async function handleSave() {
    if (sectionId) await saveSection.mutateAsync({ id: sectionId, content })
  }

  const wordCount = content.trim().split(/\s+/).filter(Boolean).length

  // A malformed route param (e.g. /proposals/undefined/workspace) is a broken
  // link, not an empty workspace — don't dress it up as "no requirements yet".
  if (!isValidId(id)) {
    return (
      <div className="page-padding">
        <ErrorState
          title="This workspace link is invalid"
          message="The proposal id is missing from the URL. Open the proposal from the dashboard."
        />
      </div>
    )
  }

  if (isError) {
    return (
      <div className="page-padding">
        <ErrorState title="Could not load this workspace" error={error} onRetry={() => refetch()} />
      </div>
    )
  }

  return (
    <div className="flex" style={{ height: 'calc(100vh - 88px)' }}>
      {/* Left panel — requirements grouped by category */}
      <div className="w-72 shrink-0 border-r border-neutral-100 bg-white flex flex-col">
        <div className="flex items-center justify-between px-3 py-2.5 border-b border-neutral-100">
          <span className="text-xs font-medium text-neutral-800">Grouped Requirements</span>
          <span className="text-[10px] text-neutral-400">{requirements.length}</span>
        </div>
        <div className="flex-1 overflow-y-auto">
          {isLoading && (
            <p className="px-4 py-6 text-xs text-neutral-400">Loading requirements…</p>
          )}
          {!isLoading && groups.length === 0 && (
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

      {/* Middle panel — sections drafted by the AI writer agent */}
      <div className="w-72 shrink-0 border-r border-neutral-100 bg-white flex flex-col">
        <div className="flex items-center justify-between px-3 py-2.5 border-b border-neutral-100">
          <span className="text-xs font-medium text-neutral-800">Drafted Sections</span>
          <span className="text-[10px] text-neutral-400">{sections.length}</span>
        </div>
        <div className="flex-1 overflow-y-auto">
          {sections.length === 0 && (
            <p className="px-4 py-6 text-xs text-neutral-400">
              No sections yet — click <span className="font-medium">Generate Full Draft</span> to draft every section from the requirements.
            </p>
          )}
          {sections.map((s) => (
            <button
              key={s.id}
              onClick={() => openSection(s)}
              className={cn(
                'w-full text-left px-4 py-2.5 border-b border-neutral-50 transition-colors',
                s.id === sectionId
                  ? 'bg-primary-50 border-l-2 border-l-primary-600'
                  : 'hover:bg-neutral-50'
              )}
            >
              <div className="flex items-center justify-between gap-2">
                <span className="text-xs font-medium text-neutral-800 truncate">{s.title}</span>
                <span className={cn('text-[9px] px-1.5 py-0.5 rounded-full shrink-0', sectionStatusClass(s.status))}>
                  {s.status.replace('_', ' ')}
                </span>
              </div>
              {s.reviewNotes && (
                <p className="text-[10px] text-amber-600 mt-1 line-clamp-2">⚠ {s.reviewNotes}</p>
              )}
            </button>
          ))}
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
          {/* Full drafting agent: plans + drafts every section from the extracted
              requirements. Disabled until the RFP has requirements to draft from. */}
          <Button
            variant="default"
            size="sm"
            icon={draft.status === 'drafting' ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Sparkles className="w-3.5 h-3.5" />}
            disabled={draft.status === 'drafting' || requirements.length === 0 || !isValidId(rfpId)}
            onClick={draft.generate}
          >
            {draft.status === 'drafting' ? 'Drafting…' : 'Generate Full Draft'}
          </Button>
          <div className="ml-auto flex items-center gap-3">
            {draft.status === 'drafting' && (
              <span className="text-xs text-neutral-400">Drafting all sections — this can take a few minutes.</span>
            )}
            {draft.status === 'failed' && <span className="text-xs text-danger-600">{draft.error}</span>}
            {generate.isError && <span className="text-xs text-danger-600">Generation failed</span>}
          </div>
        </div>

        <div className="flex-1 overflow-y-auto p-5">
          <h2 className="text-lg font-medium mb-2 text-neutral-800">
            {openMeta
              ? openMeta.title
              : selectedReq
                ? `${selectedReq.section} — ${categoryLabel(selectedReq.category)}`
                : 'Select a requirement'}
          </h2>
          {openMeta ? (
            <div className="mb-4 flex flex-wrap items-center gap-2">
              <span className={cn('text-[10px] px-2 py-0.5 rounded-full', sectionStatusClass(openMeta.status))}>
                {openMeta.status.replace('_', ' ')}
              </span>
              {openMeta.reviewNotes && (
                <span className="text-[11px] text-amber-600">⚠ {openMeta.reviewNotes}</span>
              )}
            </div>
          ) : (
            selectedReq && (
              <p className="text-xs text-neutral-500 mb-4 p-3 bg-neutral-50 rounded-lg">{selectedReq.text}</p>
            )
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
