'use client'
import { useState } from 'react'
import { useRouter } from 'next/navigation'
import Link from 'next/link'
import { ShieldCheck, ArrowLeft, AlertTriangle } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { authApi } from '@/lib/api'
import { useAuthStore } from '@/lib/stores/auth-store'

export default function RequestAccessPage() {
  const router = useRouter()
  const setSession = useAuthStore((s) => s.setSession)
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [org, setOrg] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError('')
    if (!name || !email || !password) {
      setError('Name, email, and password are required.')
      return
    }
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
      setSession(session)
      // Cookie lets the route-guard (proxy.ts) see the session server-side.
      document.cookie = `proposalai-token=${session.accessToken}; path=/`
      router.push('/dashboard')
    } catch (err) {
      const status = (err as { response?: { status?: number } }).response?.status
      setError(
        status === 409 ? 'An account with that email already exists.'
        : 'Could not create your account. Please try again.'
      )
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
          <Input label="Full name"    type="text"     placeholder="Jane Smith"       value={name}     onChange={(e) => setName(e.target.value)} />
          <Input label="Work email"   type="email"    placeholder="jane@company.gov" value={email}    onChange={(e) => setEmail(e.target.value)} />
          <Input label="Password"     type="password" placeholder="••••••••"          value={password} onChange={(e) => setPassword(e.target.value)} />
          <Input label="Organization" type="text"     placeholder="Acro Inc."        value={org}      onChange={(e) => setOrg(e.target.value)} />
        </div>

        {error && (
          <div className="flex items-center gap-2 mb-4 px-3 py-2.5 bg-danger-50 border border-danger-200 rounded-lg">
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
