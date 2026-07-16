'use client'
import { useState } from 'react'
import { X, Lock } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input, Textarea, Select } from '@/components/ui/input'
import { Card } from '@/components/ui/card'
import { useProfile, useSaveProfile } from '@/lib/hooks'
import type { CompanyProfile } from '@/types'

export default function ProfilePage() {
  const { data: profile } = useProfile()
  if (!profile) return null
  // Re-mount the form when real data replaces the loading placeholder so the
  // uncontrolled inputs pick up fresh defaults.
  return <ProfileForm key={profile.id} profile={profile} />
}

function ProfileForm({ profile }: { profile: CompanyProfile }) {
  const [socio, setSocio] = useState(profile.socioEconomicStatus)
  const [socioInput, setSocioInput] = useState('')
  const save = useSaveProfile()

  function addSocio() {
    if (socioInput.trim()) { setSocio([...socio, socioInput.trim()]); setSocioInput('') }
  }

  function handleSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault()
    const fd = new FormData(e.currentTarget)
    const str = (k: string) => { const v = fd.get(k); return v === null ? undefined : String(v) }
    const num = (k: string) => { const v = fd.get(k); return v === null || v === '' ? undefined : Number(v) }
    const revM = fd.get('annualRevenueMillions')
    // Partial update — the backend merges, so omitted fields (certs, past
    // performance, capabilities…) are preserved.
    save.mutate({
      legalName: str('legalName'),
      dunsNumber: str('dunsNumber'),
      ueiNumber: str('ueiNumber'),
      primaryAddress: str('primaryAddress'),
      naicsCode: str('naicsCode'),
      cmmcLevel: str('cmmcLevel'),
      socioEconomicStatus: socio,
      annualRevenue: revM !== null && revM !== '' ? Number(revM) * 1_000_000 : undefined,
      fringeRate: num('fringeRate'),
      overheadRate: num('overheadRate'),
      gaRate: num('gaRate'),
    })
  }

  return (
    <form onSubmit={handleSubmit} className="content-narrow">
      <h1 className="text-lg font-medium mb-1">Company Profile</h1>
      <p className="text-xs text-[var(--text-secondary)] mb-5">Stored once — reused across every winning proposal.</p>

      <Card className="mb-4">
        {/* Company identity */}
        <p className="text-[10px] font-medium text-primary-600 tracking-wider uppercase mb-3">Company Identity</p>
        <div className="grid grid-cols-2 gap-3 mb-4">
          <div className="col-span-2">
            <Input label="Legal Entity Name" name="legalName" defaultValue={profile.legalName} />
          </div>
          <Input label="DUNS Number" name="dunsNumber" defaultValue={profile.dunsNumber} />
          <Input label="UEI Number"  name="ueiNumber" defaultValue={profile.ueiNumber} />
          <div className="col-span-2">
            <Textarea label="Primary Address" name="primaryAddress" defaultValue={profile.primaryAddress} rows={2} />
          </div>
        </div>

        <div className="border-t border-[var(--border-subtle)] pt-4 mb-4">
          <p className="text-[10px] font-medium text-primary-600 tracking-wider uppercase mb-3">Capabilities &amp; Certs</p>
          <div className="grid grid-cols-2 gap-3 mb-3">
            <Select label="Primary NAICS Code" name="naicsCode" defaultValue={profile.naicsCode || '541512'} options={[
              { value: '541512', label: '541512 - Computer Systems Design' },
              { value: '811310', label: '811310 - Commercial Machinery Repair' },
              { value: '561210', label: '561210 - Facilities Management' },
            ]} />
            <Select label="CMMC Level" name="cmmcLevel" defaultValue={profile.cmmcLevel || '2'} options={[
              { value: '1', label: 'Level 1 (Foundational)' },
              { value: '2', label: 'Level 2 (Advanced)' },
              { value: '3', label: 'Level 3 (Expert)' },
            ]} />
          </div>
          <div>
            <p className="text-xs text-[var(--text-secondary)] mb-1.5">Socio-economic Status</p>
            <div className="flex flex-wrap gap-1.5">
              {socio.map((s) => (
                <span key={s} className="inline-flex items-center gap-1 px-2 py-0.5 bg-[var(--bg-secondary)] border border-[var(--border-default)] rounded text-xs">
                  {s}
                  <button type="button" onClick={() => setSocio(socio.filter((x) => x !== s))} className="text-[var(--text-tertiary)] hover:text-danger-600">
                    <X className="w-3 h-3" />
                  </button>
                </span>
              ))}
              <div className="flex items-center gap-1">
                <input
                  value={socioInput}
                  onChange={(e) => setSocioInput(e.target.value)}
                  onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); addSocio() } }}
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
            <Input label="Annual Revenue (3yr Avg, $M)" name="annualRevenueMillions" type="number" step="0.1" defaultValue={profile.annualRevenue / 1000000} />
            <Input label="Fringe Rate"   name="fringeRate" type="number" defaultValue={profile.fringeRate} />
            <Input label="Overhead Rate" name="overheadRate" type="number" defaultValue={profile.overheadRate} />
            <Input label="G&A Rate"      name="gaRate" type="number" defaultValue={profile.gaRate} />
          </div>
        </div>

        <div className="flex items-center justify-end gap-3 mt-5">
          {save.isError && <span className="text-xs text-danger-600 mr-auto">Could not save — please try again.</span>}
          {save.isSuccess && !save.isPending && <span className="text-xs text-success-600 mr-auto">Profile saved.</span>}
          <Button type="button" variant="default">Cancel</Button>
          <Button type="submit" variant="primary" loading={save.isPending}>Save Profile</Button>
        </div>
      </Card>

      {/* Security note */}
      <div className="flex items-center gap-2 px-4 py-3 bg-[var(--bg-secondary)] border border-[var(--border-subtle)] rounded-xl text-xs text-[var(--text-secondary)]">
        <Lock className="w-3.5 h-3.5 shrink-0" />
        All financial and legal data is encrypted at rest and only accessible to authorized proposal managers during the generation phase.
      </div>
    </form>
  )
}
