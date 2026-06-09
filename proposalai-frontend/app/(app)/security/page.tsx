import { Card } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { ShieldCheck, Key, Smartphone } from 'lucide-react'

export default function SecurityPage() {
  return (
    <div className="content-narrow">
      <h1 className="text-lg font-medium mb-1">Security</h1>
      <p className="text-xs text-[var(--text-secondary)] mb-5">Manage your account security settings.</p>

      <Card className="mb-4">
        <div className="flex items-center gap-3 mb-4">
          <div className="w-8 h-8 rounded-lg bg-primary-50 flex items-center justify-center">
            <Key className="w-4 h-4 text-primary-600" />
          </div>
          <div>
            <p className="text-sm font-medium">Change password</p>
            <p className="text-xs text-[var(--text-tertiary)]">Update your login password</p>
          </div>
        </div>
        <div className="flex flex-col gap-3">
          <Input label="Current password"  type="password" placeholder="••••••••" />
          <Input label="New password"      type="password" placeholder="••••••••" />
          <Input label="Confirm password"  type="password" placeholder="••••••••" />
        </div>
        <div className="flex justify-end mt-4">
          <Button variant="primary" size="sm">Update password</Button>
        </div>
      </Card>

      <Card className="mb-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-lg bg-success-50 flex items-center justify-center">
              <Smartphone className="w-4 h-4 text-success-400" />
            </div>
            <div>
              <p className="text-sm font-medium">Two-factor authentication</p>
              <p className="text-xs text-[var(--text-tertiary)]">Add an extra layer of security</p>
            </div>
          </div>
          <Button variant="default" size="sm">Enable</Button>
        </div>
      </Card>

      <Card>
        <div className="flex items-center gap-3 mb-3">
          <div className="w-8 h-8 rounded-lg bg-[var(--bg-secondary)] flex items-center justify-center">
            <ShieldCheck className="w-4 h-4 text-[var(--text-secondary)]" />
          </div>
          <div>
            <p className="text-sm font-medium">Active sessions</p>
            <p className="text-xs text-[var(--text-tertiary)]">Devices currently signed in</p>
          </div>
        </div>
        <div className="flex items-center justify-between py-2 border-t border-[var(--border-subtle)]">
          <div>
            <p className="text-xs font-medium">Chrome on macOS</p>
            <p className="text-[10px] text-[var(--text-tertiary)]">Arlington, VA · Active now</p>
          </div>
          <span className="text-[10px] px-2 py-0.5 bg-success-50 text-success-600 rounded font-medium">Current</span>
        </div>
      </Card>
    </div>
  )
}