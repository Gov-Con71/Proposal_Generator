'use client'
import { useState } from 'react'
import { useRouter } from 'next/navigation'
import Link from 'next/link'
import { authApi } from '@/lib/api'
import { useAuthStore } from '@/lib/stores/auth-store'

export default function LoginPage() {
  const router = useRouter()
  const setSession = useAuthStore((s) => s.setSession)
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError('')
    if (!email || !password) {
      setError('Please enter your email and password.')
      return
    }
    setLoading(true)
    try {
      const session = await authApi.login(email, password)
      setSession(session)
      // Cookie lets the route-guard (proxy.ts) see the session server-side.
      document.cookie = `proposalai-token=${session.accessToken}; path=/`
      router.push('/dashboard')
    } catch (err) {
      const status = (err as { response?: { status?: number } }).response?.status
      setError(status === 401 ? 'Incorrect email or password.' : 'Sign in failed. Please try again.')
      setLoading(false)
    }
  }

  return (
    <div style={{
      minHeight: '100vh',
      backgroundColor: '#F5F5F4',
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
      justifyContent: 'center',
      padding: '16px',
      fontFamily: 'Inter, system-ui, sans-serif',
    }}>
      <div style={{
        width: '100%',
        maxWidth: '360px',
        backgroundColor: '#FFFFFF',
        border: '1px solid rgba(0,0,0,0.08)',
        borderRadius: '16px',
        padding: '32px',
      }}>
        {/* Logo */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '24px' }}>
          <div style={{
            width: '32px', height: '32px',
            backgroundColor: '#185FA5',
            borderRadius: '8px',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
          }}>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2">
              <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
            </svg>
          </div>
          <span style={{ fontSize: '15px', fontWeight: '500', color: '#1C1C1A' }}>ProposalAI</span>
        </div>

        <h1 style={{ fontSize: '18px', fontWeight: '500', color: '#1C1C1A', marginBottom: '4px' }}>Sign in</h1>
        <p style={{ fontSize: '12px', color: '#888780', marginBottom: '24px' }}>
          Government Proposal Generation Platform
        </p>

        {error && (
          <div style={{
            marginBottom: '16px',
            padding: '10px 12px',
            backgroundColor: '#FCEBEB',
            border: '1px solid #F7C1C1',
            borderRadius: '8px',
            fontSize: '12px',
            color: '#791F1F',
          }}>
            {error}
          </div>
        )}

        <form onSubmit={handleSubmit}>
          {/* Email */}
          <div style={{ marginBottom: '12px' }}>
            <label style={{ display: 'block', fontSize: '11px', color: '#5F5E5A', fontWeight: '500', marginBottom: '4px' }}>
              Email address
            </label>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="analyst@agency.gov"
              required
              style={{
                width: '100%',
                height: '34px',
                padding: '0 10px',
                fontSize: '12px',
                color: '#1C1C1A',
                backgroundColor: '#FFFFFF',
                border: '1px solid rgba(0,0,0,0.15)',
                borderRadius: '6px',
                outline: 'none',
                boxSizing: 'border-box',
              }}
            />
          </div>

          {/* Password */}
          <div style={{ marginBottom: '12px' }}>
            <label style={{ display: 'block', fontSize: '11px', color: '#5F5E5A', fontWeight: '500', marginBottom: '4px' }}>
              Password
            </label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="••••••••"
              required
              style={{
                width: '100%',
                height: '34px',
                padding: '0 10px',
                fontSize: '12px',
                color: '#1C1C1A',
                backgroundColor: '#FFFFFF',
                border: '1px solid rgba(0,0,0,0.15)',
                borderRadius: '6px',
                outline: 'none',
                boxSizing: 'border-box',
              }}
            />
          </div>

          {/* Remember me + Forgot */}
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '20px' }}>
            <label style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '12px', color: '#5F5E5A', cursor: 'pointer' }}>
              <input type="checkbox" style={{ width: '13px', height: '13px', accentColor: '#185FA5' }} />
              Remember me
            </label>
            <Link href="/request-access" style={{ fontSize: '12px', color: '#185FA5' }}>
              Forgot password?
            </Link>
          </div>

          {/* Submit */}
          <button
            type="submit"
            disabled={loading}
            style={{
              width: '100%',
              height: '36px',
              backgroundColor: loading ? '#B5D4F4' : '#185FA5',
              color: '#FFFFFF',
              border: 'none',
              borderRadius: '8px',
              fontSize: '13px',
              fontWeight: '500',
              cursor: loading ? 'not-allowed' : 'pointer',
              marginBottom: '20px',
            }}
          >
            {loading ? 'Signing in...' : 'Sign in'}
          </button>
        </form>

        {/* Divider */}
        <div style={{ borderTop: '1px solid rgba(0,0,0,0.08)', marginBottom: '16px' }} />

        <p style={{ fontSize: '12px', textAlign: 'center', color: '#888780' }}>
          Need an account?{' '}
          <Link href="/request-access" style={{ color: '#185FA5' }}>
            Request access
          </Link>
        </p>
      </div>

      {/* Footer */}
      <div style={{ marginTop: '24px', display: 'flex', alignItems: 'center', gap: '6px', fontSize: '10px', color: '#888780', textTransform: 'uppercase', letterSpacing: '0.06em' }}>
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <rect x="3" y="11" width="18" height="11" rx="2" ry="2"/>
          <path d="M7 11V7a5 5 0 0 1 10 0v4"/>
        </svg>
        Session Encrypted (AES-256)
      </div>
    </div>
  )
}