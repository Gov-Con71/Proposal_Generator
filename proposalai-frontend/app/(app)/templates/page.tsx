import { Card } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { FileText, Plus } from 'lucide-react'

const TEMPLATES = [
  { id: '1', name: 'DoD IT Services',         sections: 8,  lastUsed: '2 weeks ago' },
  { id: '2', name: 'Equipment Overhaul (FFP)', sections: 6,  lastUsed: '1 month ago' },
  { id: '3', name: 'Professional Services',    sections: 10, lastUsed: 'Never' },
  { id: '4', name: 'Facility Management',      sections: 7,  lastUsed: '3 months ago' },
]

export default function TemplatesPage() {
  return (
    <div className="page-padding">
      <div className="flex items-center justify-between mb-5">
        <div>
          <h1 className="text-lg font-medium">Templates</h1>
          <p className="text-xs text-[var(--text-secondary)] mt-0.5">Reusable proposal structures</p>
        </div>
        <Button variant="primary" size="sm" icon={<Plus className="w-3.5 h-3.5" />}>New template</Button>
      </div>
      <div className="grid grid-cols-2 gap-3">
        {TEMPLATES.map((t) => (
          <Card key={t.id} className="flex items-center gap-3 cursor-pointer hover:border-primary-100 transition-colors">
            <div className="w-9 h-9 rounded-lg bg-primary-50 flex items-center justify-center shrink-0">
              <FileText className="w-4 h-4 text-primary-600" />
            </div>
            <div className="flex-1">
              <p className="text-sm font-medium">{t.name}</p>
              <p className="text-xs text-[var(--text-tertiary)]">{t.sections} sections · Last used {t.lastUsed}</p>
            </div>
            <Button variant="ghost" size="sm">Use</Button>
          </Card>
        ))}
      </div>
    </div>
  )
}