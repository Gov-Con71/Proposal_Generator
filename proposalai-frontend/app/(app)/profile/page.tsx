'use client'
import { useState } from 'react'
import { X, Plus, Lock } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input, Textarea, Select } from '@/components/ui/input'
import { Card } from '@/components/ui/card'
import { MOCK_PROFILE } from '@/lib/constants/mock-data'
import { cn } from '@/lib/utils/cn'

export default function ProfilePage() {
  const [certs, setCerts] = useState(MOCK_PROFILE.certifications)
  const [certInput, setCertInput] = useState('')
  const [socio, setSocio] = useState(MOCK_PROFILE.socioEconomicStatus)
  const [socioInput, setSocioInput] = useState('')

  function addCert() {
    if (certInput.trim()) { setCerts([...certs, certInput.trim()]); setCertInput('') }
  }
  function addSocio() {
    if (socioInput.trim()) { setSocio([...socio, socioInput.trim()]); setSocioInput('') }
  }

  return (
    <div className="content-narrow">
      <h1 className="text-lg font-medium mb-1">Company Profile</h1>
      <p className="text-xs text-[var(--text-secondary)] mb-5">Stored once — reused across every winning proposal.</p>

      <Card className="mb-4">
        {/* Company identity */}
        <p className="text-[10px] font-medium text-primary-600 tracking-wider uppercase mb-3">Company Identity</p>
        <div className="grid grid-cols-2 gap-3 mb-4">
          <div className="col-span-2">
            <Input label="Legal Entity Name" defaultValue={MOCK_PROFILE.legalName} />
          </div>
          <Input label="DUNS Number" defaultValue={MOCK_PROFILE.dunsNumber} />
          <Input label="UEI Number"  defaultValue={MOCK_PROFILE.ueiNumber} />
          <div className="col-span-2">
            <Textarea label="Primary Address" defaultValue={MOCK_PROFILE.primaryAddress} rows={2} />
          </div>
        </div>

        <div className="border-t border-[var(--border-subtle)] pt-4 mb-4">
          <p className="text-[10px] font-medium text-primary-600 tracking-wider uppercase mb-3">Capabilities &amp; Certs</p>
          <div className="grid grid-cols-2 gap-3 mb-3">
            <Select label="Primary NAICS Code" options={[
              { value: '541512', label: '541512 - Computer Systems Design' },
              { value: '811310', label: '811310 - Commercial Machinery Repair' },
              { value: '561210', label: '561210 - Facilities Management' },
            ]} defaultValue="541512" />
            <Select label="CMMC Level" options={[
              { value: '1', label: 'Level 1 (Foundational)' },
              { value: '2', label: 'Level 2 (Advanced)' },
              { value: '3', label: 'Level 3 (Expert)' },
            ]} defaultValue="2" />
          </div>
          <div>
            <p className="text-xs text-[var(--text-secondary)] mb-1.5">Socio-economic Status</p>
            <div className="flex flex-wrap gap-1.5">
              {socio.map((s) => (
                <span key={s} className="inline-flex items-center gap-1 px-2 py-0.5 bg-[var(--bg-secondary)] border border-[var(--border-default)] rounded text-xs">
                  {s}
                  <button onClick={() => setSocio(socio.filter((x) => x !== s))} className="text-[var(--text-tertiary)] hover:text-danger-600">
                    <X className="w-3 h-3" />
                  </button>
                </span>
              ))}
              <div className="flex items-center gap-1">
                <input
                  value={socioInput}
                  onChange={(e) => setSocioInput(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && addSocio()}
                  placeholder="+ Add Tag"
                  className="border border-dashed border-[var(--border-default)] rounded px-2 py-0.5 text-xs bg-transparent focus:outline-none focus:border-primary-600 w-20"
                />
              </div>
            </div>
          </div>
        </div>

        <div className="border-t border-[var(--border-subtle)] pt-4">
          <p className="text-[10px] font-medium text-primary-600 tracking-wider uppercase mb-3">Financial</p>
          <div className="grid grid-cols-2 gap-3">
            <Input label="Annual Revenue (3yr Avg)" defaultValue={`$${(MOCK_PROFILE.annualRevenue / 1000000).toFixed(1)}M`} />
            <Input label="Fringe Rate"   type="number" defaultValue={MOCK_PROFILE.fringeRate} />
            <Input label="Overhead Rate" type="number" defaultValue={MOCK_PROFILE.overheadRate} />
            <Input label="G&A Rate"      type="number" defaultValue={MOCK_PROFILE.gaRate} />
          </div>
        </div>

        <div className="flex justify-end gap-2 mt-5">
          <Button variant="default">Cancel</Button>
          <Button variant="primary">Save Profile</Button>
        </div>
      </Card>

      {/* Security note */}
      <div className="flex items-center gap-2 px-4 py-3 bg-[var(--bg-secondary)] border border-[var(--border-subtle)] rounded-xl text-xs text-[var(--text-secondary)]">
        <Lock className="w-3.5 h-3.5 shrink-0" />
        All financial and legal data is encrypted at rest and only accessible to authorized proposal managers during the generation phase.
      </div>
    </div>
  )
}