'use client'
import { useRef, useState } from 'react'
import { useRouter } from 'next/navigation'
import Link from 'next/link'
import { ShieldCheck, ArrowLeft, AlertTriangle } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { PasswordRequirements, usePasswordPolicy } from '@/components/ui/password-requirements'
import { authError, passwordError } from '@/lib/password-validation'
import { authApi } from '@/lib/api'
import { useAuthStore } from '@/lib/stores/auth-store'

export default function RequestAccessPage() {
  const router = useRouter()
  const setSession = useAuthStore((s) => s.setSession)
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const policy = usePasswordPolicy()
  const passwordRef = useRef<HTMLInputElement>(null)
  const [fieldError, setFieldError] = useState('')
  const [org, setOrg] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError('')
    if (!name.trim() || !email) {
      setError('Name and email are required.')
      e.currentTarget.querySelector<HTMLInputElement>(!name.trim() ? '#full-name' : '#work-email')?.focus()
      return
    }
    const invalid = passwordError(password, policy)
    setFieldError(invalid)
    if (invalid) { passwordRef.current?.focus(); return }
    const [firstName, ...rest] = name.trim().split(' ')
    setLoading(true)
    try {
      const session = await authApi.register({
        email,
        password,
        firstName,
        lastName: rest.join(' '),
        company: org.trim() || undefined,
      })
      // setSession also sets the route-guard marker cookie. The session's
      // real credential is the HttpOnly cookie the server just set, which
      // this code deliberately cannot read.
      setSession(session)
      router.push('/dashboard')
    } catch (err) {
      const failure = authError(err, 'Could not create your account. Please try again.')
      if (failure.status === 422 && (!failure.field || failure.field === 'password')) {
        setFieldError(failure.message)
        passwordRef.current?.focus()
      } else {
        setError(failure.status === 409 ? 'An account with that email already exists.' : failure.message)
      }
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-[var(--bg-secondary)] flex items-center justify-center p-4">
      <form onSubmit={handleSubmit} className="w-full max-w-sm bg-[var(--bg-primary)] border border-[var(--border-subtle)] rounded-2xl p-8 animate-fade-in">
        <div className="flex items-center gap-2.5 mb-6">
          <div className="w-8 h-8 rounded-lg bg-primary-600 flex items-center justify-center">
            <ShieldCheck className="w-4 h-4 text-white" />
          </div>
          <span className="text-base font-medium">ProposalAI</span>
        </div>

        <h1 className="text-md font-medium mb-1">Create your account</h1>
        <p className="text-xs text-[var(--text-tertiary)] mb-5">
          Set up access to start uploading and analyzing RFPs.
        </p>

        <div className="flex flex-col gap-3 mb-5">
          <Input label="Full name"    type="text"     placeholder="Jane Smith"       value={name}     onChange={(e) => { setName(e.target.value); setFieldError(''); setError('') }} />
          <Input label="Work email"   type="email"    placeholder="jane@company.gov" value={email}    onChange={(e) => { setEmail(e.target.value); setFieldError(''); setError('') }} />
          <Input label="Password"     type="password" placeholder="••••••••"          value={password} ref={passwordRef} error={fieldError} autoComplete="new-password"
            aria-describedby="register-password-requirements"
            onChange={(e) => { setPassword(e.target.value); setFieldError('') }} />
          <PasswordRequirements id="register-password-requirements" password={password} policy={policy} registration />
          <Input label="Organization" type="text"     placeholder="Acro Inc."        value={org}      onChange={(e) => setOrg(e.target.value)} />
        </div>

        {error && (
          <div role="alert" className="flex items-center gap-2 mb-4 px-3 py-2.5 bg-danger-50 border border-danger-200 rounded-lg">
            <AlertTriangle className="w-4 h-4 text-danger-600 shrink-0" />
            <p className="text-xs text-danger-700">{error}</p>
          </div>
        )}

        <Button type="submit" variant="primary" size="lg" className="w-full mb-3" disabled={loading}>
          {loading ? 'Creating account…' : 'Create account'}
        </Button>

        <Link href="/login" className="flex items-center justify-center gap-1.5 text-xs text-[var(--text-secondary)] hover:text-[var(--text-primary)] transition-colors">
          <ArrowLeft className="w-3.5 h-3.5" /> Back to sign in
        </Link>
      </form>
    </div>
  )
}
