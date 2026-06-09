'use client'
import { useState } from 'react'
import { useRouter } from 'next/navigation'
import { ArrowLeft, Plus, X, Trash2 } from 'lucide-react'
import Link from 'next/link'
import { Button } from '@/components/ui/button'
import { Input, Textarea, Select } from '@/components/ui/input'
import { Card, StepIndicator } from '@/components/ui/card'
import { MOCK_PROFILE } from '@/lib/constants/mock-data'
import type { Step } from '@/components/ui/card'

const STEPS: Step[] = [
  { label: 'Upload RFP', status: 'done' },
  { label: 'Analyze',    status: 'active' },
  { label: 'Outline',    status: 'pending' },
  { label: 'Review',     status: 'pending' },
]

export default function AnalyzePage() {
  const router = useRouter()
  const [certs, setCerts] = useState(MOCK_PROFILE.certifications)
  const [certInput, setCertInput] = useState('')
  const [socio, setSocio] = useState(MOCK_PROFILE.socioEconomicStatus)
  const [socioInput, setSocioInput] = useState('')
  const [pastPerf, setPastPerf] = useState(MOCK_PROFILE.pastPerformance)
  const [draftingLevel, setDraftingLevel] = useState<'technical' | 'executive'>('technical')

  function addCert() {
    if (certInput.trim()) { setCerts([...certs, certInput.trim()]); setCertInput('') }
  }
  function removeCert(c: string) { setCerts(certs.filter((x) => x !== c)) }
  function addSocio() {
    if (socioInput.trim()) { setSocio([...socio, socioInput.trim()]); setSocioInput('') }
  }
  function removeSocio(s: string) { setSocio(socio.filter((x) => x !== s)) }
  function removePast(id: string) { setPastPerf(pastPerf.filter((p) => p.id !== id)) }

  return (
    <div className="content-narrow">
      <Link href="/proposals/new" className="inline-flex items-center gap-1.5 text-xs text-[var(--text-secondary)] hover:text-[var(--text-primary)] mb-4 transition-colors">
        <ArrowLeft className="w-3.5 h-3.5" /> Back
      </Link>

      <StepIndicator steps={STEPS} className="mb-6" />

      <h1 className="text-lg font-medium mb-1">Proposal Context</h1>
      <p className="text-xs text-[var(--text-secondary)] mb-5">Provide the foundational organizational and technical data for the AI engine.</p>

      {/* Company identity */}
      <Card className="mb-4">
        <p className="text-[10px] font-medium text-primary-600 tracking-wider uppercase mb-3">Company Identity</p>
        <div className="grid grid-cols-2 gap-3">
          <div className="col-span-2">
            <Input label="Legal Entity Name" defaultValue={MOCK_PROFILE.legalName} />
          </div>
          <Input label="CAGE Code"   defaultValue={MOCK_PROFILE.cageCode} />
          <Input label="UEI Number"  defaultValue={MOCK_PROFILE.ueiNumber} />
        </div>
      </Card>

      {/* Technical capability */}
      <Card className="mb-4">
        <p className="text-[10px] font-medium text-primary-600 tracking-wider uppercase mb-3">Technical Capability</p>
        <Textarea label="Capabilities Overview" defaultValue={MOCK_PROFILE.capabilitiesOverview} rows={4} className="mb-3" />
        <p className="text-xs text-[var(--text-secondary)] mb-2">Certifications &amp; Clearances</p>
        <div className="flex flex-wrap gap-1.5 mb-2">
          {certs.map((c) => (
            <span key={c} className="inline-flex items-center gap-1 px-2 py-0.5 bg-[var(--bg-secondary)] border border-[var(--border-default)] rounded text-xs">
              {c}
              <button onClick={() => removeCert(c)} className="text-[var(--text-tertiary)] hover:text-danger-600"><X className="w-3 h-3" /></button>
            </span>
          ))}
          <div className="flex items-center gap-1">
            <input
              value={certInput}
              onChange={(e) => setCertInput(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && addCert()}
              placeholder="+ Add cert"
              className="border border-dashed border-[var(--border-default)] rounded px-2 py-0.5 text-xs bg-transparent focus:outline-none focus:border-primary-600 w-24"
            />
          </div>
        </div>
      </Card>

      {/* Past performance */}
      <Card className="mb-4">
        <div className="flex items-center justify-between mb-3">
          <p className="text-[10px] font-medium text-primary-600 tracking-wider uppercase">Past Performance</p>
          <Button variant="default" size="sm" icon={<Plus className="w-3 h-3" />}>Add contract</Button>
        </div>
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-[var(--border-subtle)]">
              {['CONTRACT #', 'AGENCY', 'VALUE', 'SCOPE', 'PERIOD', ''].map((h) => (
                <th key={h} className="text-left text-[10px] text-[var(--text-tertiary)] font-medium pb-2 pr-3">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {pastPerf.map((p) => (
              <tr key={p.id} className="border-b border-[var(--border-subtle)] last:border-0">
                <td className="py-2 pr-3 font-medium">{p.contractNumber}</td>
                <td className="py-2 pr-3 text-[var(--text-secondary)]">{p.agency}</td>
                <td className="py-2 pr-3 text-[var(--text-secondary)]">${(p.value / 1000).toFixed(0)}K</td>
                <td className="py-2 pr-3 text-[var(--text-secondary)]">{p.scope}</td>
                <td className="py-2 pr-3 text-[var(--text-secondary)]">{p.period}</td>
                <td className="py-2">
                  <button onClick={() => removePast(p.id)} className="text-[var(--text-tertiary)] hover:text-danger-600 transition-colors">
                    <Trash2 className="w-3.5 h-3.5" />
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>

      {/* Pricing */}
      <Card className="mb-4">
        <p className="text-[10px] font-medium text-primary-600 tracking-wider uppercase mb-3">Pricing Structure</p>
        <div className="grid grid-cols-2 gap-3">
          <Select label="Primary Pricing Model" options={[
            { value: 'ffp', label: 'Firm Fixed Price (FFP)' },
            { value: 'cpff', label: 'Cost Plus Fixed Fee' },
            { value: 'tm', label: 'Time & Materials' },
          ]} defaultValue="ffp" />
          <Input label="Target Profit Margin (%)" type="number" defaultValue="12" />
        </div>
      </Card>

      {/* Drafting preferences */}
      <Card className="mb-6">
        <p className="text-[10px] font-medium text-primary-600 tracking-wider uppercase mb-3">Drafting Preferences</p>
        <div className="grid grid-cols-3 gap-3">
          <div>
            <p className="text-xs text-[var(--text-secondary)] mb-1.5">Drafting Level</p>
            <div className="flex rounded-md border border-[var(--border-default)] overflow-hidden w-fit">
              {(['technical', 'executive'] as const).map((l) => (
                <button
                  key={l}
                  onClick={() => setDraftingLevel(l)}
                  className={`px-3 py-1.5 text-xs capitalize transition-colors ${
                    draftingLevel === l
                      ? 'bg-primary-600 text-white'
                      : 'bg-[var(--bg-primary)] text-[var(--text-secondary)] hover:bg-[var(--bg-secondary)]'
                  }`}
                >
                  {l}
                </button>
              ))}
            </div>
          </div>
          <Select label="Tone" options={[
            { value: 'authoritative', label: 'Authoritative & Precise' },
            { value: 'narrative', label: 'Narrative-driven' },
            { value: 'hybrid', label: 'Hybrid' },
          ]} defaultValue="authoritative" />
          <Input label="Page Limit" type="number" defaultValue="25" />
        </div>
      </Card>

      <div className="flex justify-between">
        <Button variant="default" asChild><Link href="/proposals/new">Back</Link></Button>
        <div className="flex gap-2">
          <Button variant="default">Save Draft</Button>
          <Button variant="primary" onClick={() => router.push('/proposals/new/process')}>
            Generate Proposal
          </Button>
        </div>
      </div>
    </div>
  )
}