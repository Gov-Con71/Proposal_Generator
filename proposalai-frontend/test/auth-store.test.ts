/**
 * Session state.
 *
 * The point of these is regression pressure on a security property that is
 * invisible at runtime: nothing durable may hold a credential. A future `persist`
 * wrapper added for convenience would restore exactly the bug §2.5 describes,
 * and nothing else in the system would notice.
 */
import { beforeEach, describe, expect, it } from 'vitest'

import { useAuthStore } from '@/lib/stores/auth-store'

const SESSION = {
  user: { id: 'u1', email: 'a@b.c', name: 'A', role: 'analyst', companyId: '', createdAt: '' },
  accessToken: 'in-memory-only',
  expiresAt: '2099-01-01T00:00:00Z',
} as never

beforeEach(() => {
  useAuthStore.getState().clearSession()
  localStorage.clear()
  sessionStorage.clear()
})

describe('credential handling', () => {
  it('never writes a token to storage', () => {
    useAuthStore.getState().setSession(SESSION)

    const dumped = JSON.stringify(localStorage) + JSON.stringify(sessionStorage)
    expect(dumped).not.toContain('in-memory-only')
    expect(localStorage.length).toBe(0)
    expect(sessionStorage.length).toBe(0)
  })

  it('never writes a token to a cookie', () => {
    useAuthStore.getState().setSession(SESSION)

    // The marker exists; the token must not be in it. The access token used to
    // be written to `proposalai-token` with document.cookie, readable by any
    // script on the page.
    expect(document.cookie).toContain('proposalai-authed=1')
    expect(document.cookie).not.toContain('in-memory-only')
  })

  it('holds the access token in memory', () => {
    useAuthStore.getState().setSession(SESSION)
    expect(useAuthStore.getState().accessToken).toBe('in-memory-only')
    expect(useAuthStore.getState().isAuthenticated).toBe(true)
  })
})

describe('lifecycle', () => {
  it('clears the marker on sign-out so the route guard redirects', () => {
    useAuthStore.getState().setSession(SESSION)
    useAuthStore.getState().clearSession()

    expect(document.cookie).not.toContain('proposalai-authed=1')
    expect(useAuthStore.getState().accessToken).toBeNull()
    expect(useAuthStore.getState().user).toBeNull()
    expect(useAuthStore.getState().isAuthenticated).toBe(false)
  })

  it('reports ready after either outcome', () => {
    // A guard waiting on isReady must not hang on the entirely normal path of a
    // visitor who is simply not signed in.
    expect(useAuthStore.getState().isReady).toBe(true)

    useAuthStore.setState({ isReady: false })
    useAuthStore.getState().setSession(SESSION)
    expect(useAuthStore.getState().isReady).toBe(true)

    useAuthStore.setState({ isReady: false })
    useAuthStore.getState().clearSession()
    expect(useAuthStore.getState().isReady).toBe(true)
  })
})
