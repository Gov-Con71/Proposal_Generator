'use client'
import { useState } from 'react'
import { useRouter } from 'next/navigation'
import QRCode from 'qrcode'
import Image from 'next/image'
import { Card, Skeleton } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { ErrorState } from '@/components/ui/state'
import { ShieldCheck, Key, Smartphone } from 'lucide-react'
import { authApi } from '@/lib/api'
import { useAuthStore } from '@/lib/stores/auth-store'
import { useActiveSessions } from '@/lib/hooks'
import { formatRelative } from '@/lib/utils/format'
import type { ActiveSession } from '@/types'

/** No UA-parsing dependency for one label — good enough to tell devices apart. */
function describeDevice(userAgent: string | null): string {
  if (!userAgent) return 'Unknown device'
  const browser = /Edg\//.test(userAgent)
    ? 'Edge'
    : /Chrome\//.test(userAgent)
      ? 'Chrome'
      : /Firefox\//.test(userAgent)
        ? 'Firefox'
        : /Safari\//.test(userAgent)
          ? 'Safari'
          : 'Unknown browser'
  const os = /Windows/.test(userAgent)
    ? 'Windows'
    : /Mac OS X/.test(userAgent)
      ? 'macOS'
      : /Android/.test(userAgent)
        ? 'Android'
        : /iPhone|iPad/.test(userAgent)
          ? 'iOS'
          : /Linux/.test(userAgent)
            ? 'Linux'
            : 'an unknown OS'
  return `${browser} on ${os}`
}

export default function SecurityPage() {
  const router = useRouter()
  const clearSession = useAuthStore((s) => s.clearSession)
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [confirm, setConfirm] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)

  async function handleChangePassword() {
    setError(null)
    // Checked here so a typo costs a keystroke rather than a round trip; the
    // server never sees the confirmation field and enforces strength itself.
    if (next !== confirm) {
      setError('The new passwords do not match.')
      return
    }
    setSaving(true)
    try {
      await authApi.changePassword(current, next)
      // A successful change revokes every refresh token, including this tab's,
      // so there is no session left to stay in. Sending the user to sign in
      // again is the honest end state, not a courtesy.
      clearSession()
      router.push('/login?changed=1')
    } catch (err) {
      const res = (err as { response?: { status?: number; data?: { detail?: string } } }).response
      setError(
        res?.status === 401
          ? 'Your current password is incorrect.'
          : res?.data?.detail || 'Could not update your password. Please try again.'
      )
      setSaving(false)
    }
  }

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
            <p className="text-xs text-[var(--text-tertiary)]">
              Updating your password signs out every device, including this one.
            </p>
          </div>
        </div>
        <div className="flex flex-col gap-3">
          <Input
            label="Current password" type="password" placeholder="••••••••"
            value={current} onChange={(e) => setCurrent(e.target.value)}
          />
          <Input
            label="New password" type="password" placeholder="••••••••"
            value={next} onChange={(e) => setNext(e.target.value)}
          />
          <Input
            label="Confirm password" type="password" placeholder="••••••••"
            value={confirm} onChange={(e) => setConfirm(e.target.value)}
          />
        </div>
        {error && (
          <p role="alert" className="text-xs text-danger-600 mt-3">{error}</p>
        )}
        <div className="flex justify-end mt-4">
          <Button
            variant="primary" size="sm"
            onClick={handleChangePassword}
            disabled={saving || !current || !next || !confirm}
          >
            {saving ? 'Updating…' : 'Update password'}
          </Button>
        </div>
      </Card>

      <TwoFactorCard />

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
        <ActiveSessionsList />
      </Card>
    </div>
  )
}

function ActiveSessionsList() {
  const { data: sessions, isLoading, isError, error, refetch } = useActiveSessions()

  if (isLoading) {
    return (
      <div className="flex flex-col gap-2 pt-1">
        {Array.from({ length: 2 }).map((_, i) => (
          <Skeleton key={i} height={36} className="border-t border-[var(--border-subtle)]" />
        ))}
      </div>
    )
  }
  if (isError) {
    return <ErrorState title="Could not load active sessions" error={error} onRetry={() => refetch()} />
  }
  if (!sessions || sessions.length === 0) {
    return <p className="text-xs text-[var(--text-tertiary)] py-2 border-t border-[var(--border-subtle)]">No active sessions.</p>
  }
  return (
    <>
      {sessions.map((s: ActiveSession) => (
        <div key={s.id} className="flex items-center justify-between py-2 border-t border-[var(--border-subtle)]">
          <div>
            <p className="text-xs font-medium">{describeDevice(s.userAgent)}</p>
            <p className="text-[10px] text-[var(--text-tertiary)]">
              {s.ipAddress ?? 'Unknown location'} · {s.isCurrent ? 'Active now' : formatRelative(s.createdAt)}
            </p>
          </div>
          {s.isCurrent && (
            <span className="text-[10px] px-2 py-0.5 bg-success-50 text-success-600 rounded font-medium">Current</span>
          )}
        </div>
      ))}
    </>
  )
}

type TwoFactorMode = 'idle' | 'enrolling' | 'disabling'

function TwoFactorCard() {
  const user = useAuthStore((s) => s.user)
  const updateUser = useAuthStore((s) => s.updateUser)
  const [mode, setMode] = useState<TwoFactorMode>('idle')
  const [setup, setSetup] = useState<{ secret: string; qrDataUrl: string } | null>(null)
  const [code, setCode] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  function reset() {
    setMode('idle')
    setSetup(null)
    setCode('')
    setPassword('')
    setError(null)
    setBusy(false)
  }

  async function startEnroll() {
    setError(null)
    setBusy(true)
    try {
      const { secret, otpauthUrl } = await authApi.setupTwoFactor()
      const qrDataUrl = await QRCode.toDataURL(otpauthUrl)
      setSetup({ secret, qrDataUrl })
      setMode('enrolling')
    } catch {
      setError('Could not start enrollment. Please try again.')
    } finally {
      setBusy(false)
    }
  }

  async function confirmEnroll() {
    setError(null)
    setBusy(true)
    try {
      await authApi.verifyTwoFactor(code)
      updateUser({ totpEnabled: true })
      reset()
    } catch (err) {
      const status = (err as { response?: { status?: number } }).response?.status
      setError(status === 400 ? 'Incorrect code. Check your authenticator app and try again.' : 'Could not confirm. Please try again.')
      setBusy(false)
    }
  }

  async function confirmDisable() {
    setError(null)
    setBusy(true)
    try {
      await authApi.disableTwoFactor(password)
      updateUser({ totpEnabled: false })
      reset()
    } catch (err) {
      const status = (err as { response?: { status?: number } }).response?.status
      setError(status === 401 ? 'Your password is incorrect.' : 'Could not disable. Please try again.')
      setBusy(false)
    }
  }

  return (
    <Card className="mb-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg bg-success-50 flex items-center justify-center">
            <Smartphone className="w-4 h-4 text-success-400" />
          </div>
          <div>
            <p className="text-sm font-medium">Two-factor authentication</p>
            <p className="text-xs text-[var(--text-tertiary)]">
              {user?.totpEnabled ? 'Enabled — codes come from your authenticator app.' : 'Add an extra layer of security'}
            </p>
          </div>
        </div>
        {mode === 'idle' && (
          user?.totpEnabled ? (
            <Button variant="default" size="sm" onClick={() => setMode('disabling')}>Disable</Button>
          ) : (
            <Button variant="default" size="sm" loading={busy} onClick={startEnroll}>Enable</Button>
          )
        )}
      </div>

      {mode === 'enrolling' && setup && (
        <div className="mt-4 pt-4 border-t border-[var(--border-subtle)] flex flex-col gap-3">
          <p className="text-xs text-[var(--text-secondary)]">
            Scan this with your authenticator app (Google Authenticator, Authy, 1Password…), or enter the code manually.
          </p>
          <Image unoptimized width={144} height={144} src={setup.qrDataUrl} alt="2FA QR code" className="w-36 h-36 rounded-lg border border-[var(--border-subtle)]" />
          <p className="text-[10px] font-mono tracking-wider text-[var(--text-tertiary)] break-all">{setup.secret}</p>
          <Input
            label="6-digit code" value={code}
            onChange={(e) => setCode(e.target.value.replace(/\D/g, '').slice(0, 6))}
            placeholder="000000"
          />
          {error && <p role="alert" className="text-xs text-danger-600">{error}</p>}
          <div className="flex justify-end gap-2">
            <Button variant="default" size="sm" onClick={reset}>Cancel</Button>
            <Button variant="primary" size="sm" loading={busy} disabled={code.length !== 6} onClick={confirmEnroll}>
              Confirm
            </Button>
          </div>
        </div>
      )}

      {mode === 'disabling' && (
        <div className="mt-4 pt-4 border-t border-[var(--border-subtle)] flex flex-col gap-3">
          <Input
            label="Password" type="password" value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="••••••••"
          />
          {error && <p role="alert" className="text-xs text-danger-600">{error}</p>}
          <div className="flex justify-end gap-2">
            <Button variant="default" size="sm" onClick={reset}>Cancel</Button>
            <Button variant="primary" size="sm" loading={busy} disabled={!password} onClick={confirmDisable}>
              Disable
            </Button>
          </div>
        </div>
      )}
    </Card>
  )
}