/**
 * The axios auth interceptor.
 *
 * This is the highest-consequence untested code on the client: it decides when
 * a session is refreshed, when the user is thrown back to the login page, and —
 * critically — that two concurrent 401s do not both spend the rotating refresh
 * token. Spending it twice is not a slow path, it is a *logout*: the second use
 * looks like a replay to the server, which revokes the whole token family.
 */
import { setupServer } from 'msw/node'
import { http, HttpResponse } from 'msw'
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'

const API = 'http://api.test'

let refreshCalls = 0
let refreshShouldFail = false
let protectedShouldSucceed = false

const server = setupServer(
  http.post(`${API}/auth/refresh`, () => {
    refreshCalls += 1
    if (refreshShouldFail) {
      return HttpResponse.json({ detail: 'Invalid or expired session.' }, { status: 401 })
    }
    protectedShouldSucceed = true
    return HttpResponse.json({
      user: { id: 'u1', email: 'a@b.c', name: 'A', role: 'analyst', companyId: '', createdAt: '' },
      accessToken: `fresh-token-${refreshCalls}`,
      expiresAt: '2099-01-01T00:00:00Z',
    })
  }),
  http.get(`${API}/protected`, () =>
    protectedShouldSucceed
      ? HttpResponse.json({ ok: true })
      : HttpResponse.json({ detail: 'expired' }, { status: 401 })
  ),
  http.post(`${API}/auth/login`, () =>
    HttpResponse.json({ detail: 'Incorrect email or password.' }, { status: 401 })
  )
)

beforeAll(() => server.listen({ onUnhandledRequest: 'error' }))
afterAll(() => server.close())

beforeEach(() => {
  refreshCalls = 0
  refreshShouldFail = false
  protectedShouldSucceed = false
  vi.resetModules() // the client holds module-level in-flight refresh state
})
afterEach(() => server.resetHandlers())

async function loadClient() {
  const mod = await import('@/lib/api/client')
  const store = await import('@/lib/stores/auth-store')
  return { ...mod, useAuthStore: store.useAuthStore }
}

describe('401 handling', () => {
  it('refreshes once and replays the original request', async () => {
    const { apiClient } = await loadClient()

    const res = await apiClient.get('/protected')

    expect(res.data).toEqual({ ok: true })
    expect(refreshCalls).toBe(1)
  })

  it('shares one refresh between concurrent 401s', async () => {
    // Two requests failing at once must not both rotate the token. The second
    // rotation would present an already-consumed token, which the server treats
    // as a replay and answers by revoking every session for that user — so the
    // bug does not look like a race, it looks like a random forced logout.
    const { apiClient } = await loadClient()

    const [a, b] = await Promise.all([
      apiClient.get('/protected'),
      apiClient.get('/protected'),
    ])

    expect(a.data).toEqual({ ok: true })
    expect(b.data).toEqual({ ok: true })
    expect(refreshCalls).toBe(1)
  })

  it('does not try to refresh a failed login', async () => {
    // A 401 here means "wrong password", not "session expired". Refreshing
    // would swallow the error the sign-in form has to display.
    const { apiClient } = await loadClient()

    await expect(
      apiClient.post('/auth/login', { email: 'a@b.c', password: 'nope' })
    ).rejects.toMatchObject({ response: { status: 401 } })
    expect(refreshCalls).toBe(0)
  })

  it('clears the session when the refresh itself is rejected', async () => {
    refreshShouldFail = true
    const { apiClient, useAuthStore } = await loadClient()
    useAuthStore.getState().setSession({
      user: { id: 'u1' },
      accessToken: 'stale',
      expiresAt: '',
    } as never)

    await expect(apiClient.get('/protected')).rejects.toBeTruthy()

    expect(useAuthStore.getState().isAuthenticated).toBe(false)
    expect(useAuthStore.getState().accessToken).toBeNull()
  })
})

describe('request authorisation', () => {
  it('attaches the in-memory access token', async () => {
    const { apiClient, useAuthStore } = await loadClient()
    useAuthStore.getState().setSession({
      user: { id: 'u1' },
      accessToken: 'in-memory-token',
      expiresAt: '',
    } as never)

    let seen: string | null = null
    server.use(
      http.get(`${API}/protected`, ({ request }) => {
        seen = request.headers.get('authorization')
        return HttpResponse.json({ ok: true })
      })
    )

    await apiClient.get('/protected')
    expect(seen).toBe('Bearer in-memory-token')
  })

  it('sends credentials so the HttpOnly refresh cookie travels', async () => {
    // withCredentials is load-bearing, not incidental: without it the browser
    // omits the cookie cross-origin and every refresh 401s, while login still
    // appears to work. Exactly the production failure DEPLOYMENT.md §2 warns of.
    const { apiClient } = await loadClient()
    expect(apiClient.defaults.withCredentials).toBe(true)
  })
})

describe('bootstrapSession', () => {
  it('restores a session from the refresh cookie', async () => {
    const { bootstrapSession, useAuthStore } = await loadClient()

    await bootstrapSession()

    expect(useAuthStore.getState().isAuthenticated).toBe(true)
    expect(useAuthStore.getState().accessToken).toBe('fresh-token-1')
    expect(useAuthStore.getState().isReady).toBe(true)
  })

  it('settles as signed-out rather than throwing when there is no cookie', async () => {
    refreshShouldFail = true
    const { bootstrapSession, useAuthStore } = await loadClient()

    await expect(bootstrapSession()).resolves.toBeUndefined()

    expect(useAuthStore.getState().isAuthenticated).toBe(false)
    // isReady must flip either way, or a guard waiting on it hangs forever on
    // the perfectly normal path of a visitor who is simply not signed in.
    expect(useAuthStore.getState().isReady).toBe(true)
  })
})
