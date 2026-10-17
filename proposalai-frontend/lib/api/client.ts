import axios, { AxiosError, CanceledError, type InternalAxiosRequestConfig } from 'axios'
import { useAuthStore } from '@/lib/stores/auth-store'

const BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

export const apiClient = axios.create({
  baseURL: BASE_URL,
  headers: { 'Content-Type': 'application/json', 'X-CSRF-Protection': '1' },
  timeout: 30000,
  // Required for the HttpOnly refresh cookie to be sent to the API origin.
  // Without it the browser silently omits the cookie and every refresh 401s.
  withCredentials: true,
})

type SessionRequest = InternalAxiosRequestConfig & { _sessionEpoch?: number; _retried?: boolean }
const SESSION_LOCK = `proposalai-session:${BASE_URL}`

export function withSessionLock<T>(action: () => Promise<T>): Promise<T> {
  if (typeof navigator !== 'undefined' && navigator.locks) {
    return navigator.locks.request(SESSION_LOCK, () => action()).then((value) => value)
  }
  return action()
}

// Only lifecycle events cross tabs; credentials remain in memory or HttpOnly cookies.
export function announceSessionChange() {
  if (typeof window !== 'undefined' && typeof window.BroadcastChannel !== 'undefined') {
    const channel = new window.BroadcastChannel(SESSION_LOCK)
    channel.postMessage('session-changed')
    channel.close()
  }
}

export function listenForSessionChanges() {
  if (typeof window === 'undefined' || typeof window.BroadcastChannel === 'undefined') return () => {}
  const channel = new window.BroadcastChannel(SESSION_LOCK)
  channel.onmessage = () => {
    useAuthStore.getState().clearSession()
    useAuthStore.setState({ isReady: false })
    // Restore whichever account now owns the shared cookie, if any.
    void bootstrapSession()
  }
  return () => channel.close()
}

// Attach the in-memory access token to every request.
apiClient.interceptors.request.use((config) => {
  ;(config as SessionRequest)._sessionEpoch = useAuthStore.getState().epoch
  const token = useAuthStore.getState().accessToken
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  } else {
    delete config.headers.Authorization
  }
  return config
})

function toLogin() {
  useAuthStore.getState().clearSession()
  if (typeof window !== 'undefined' && !window.location.pathname.startsWith('/login')) {
    window.location.href = '/login'
  }
}

// Refresh tokens rotate, so two concurrent 401s must not both spend the stored
// token — the second would be treated as a replay and revoke every session.
// Share one in-flight refresh between all waiters instead.
let refreshInFlight: Promise<string> | null = null
let refreshEpoch: number | null = null

/**
 * Exchanges the HttpOnly refresh cookie for a new access token.
 *
 * There is no token argument any more: the browser attaches the cookie, and the
 * page cannot read it. That is the point — the credential that survives a
 * reload is one script cannot touch.
 */
export function refreshSession(): Promise<string> {
  const epoch = useAuthStore.getState().epoch
  if (refreshInFlight) {
    if (refreshEpoch === epoch) return refreshInFlight
    // A previous identity's request must finish before spending the shared cookie.
    return refreshInFlight.catch(() => undefined).then(() => refreshSession())
  }
  refreshEpoch = epoch
  refreshInFlight = withSessionLock(async () => {
    if (useAuthStore.getState().epoch !== epoch) throw new CanceledError('Session changed')
    for (let attempt = 0; ; attempt++) {
      try {
        // A bare client avoids recursively entering the 401 interceptor.
        const r = await axios.post(`${BASE_URL}/auth/refresh`, null, {
          withCredentials: true, timeout: 30000,
          headers: { 'X-CSRF-Protection': '1' },
        })
        if (useAuthStore.getState().epoch !== epoch) throw new CanceledError('Session changed')
        useAuthStore.getState().setSession(r.data)
        return r.data.accessToken as string
      } catch (error) {
        const conflict = axios.isAxiosError(error) && error.response?.status === 409 &&
          error.response.data?.detail?.code === 'refresh_in_progress'
        if (!conflict || attempt >= 3) throw error
        await new Promise((resolve) => setTimeout(resolve, 250))
        if (useAuthStore.getState().epoch !== epoch) throw new CanceledError('Session changed')
      }
    }
  }).finally(() => { refreshInFlight = null; refreshEpoch = null })

  return refreshInFlight
}

/**
 * Restores the session on page load, once.
 *
 * The access token is memory-only now, so every reload starts signed out until
 * this resolves. Failure is the normal signed-out path, not an error worth
 * showing: it just means there was no valid refresh cookie.
 */
export async function bootstrapSession(): Promise<void> {
  const epoch = useAuthStore.getState().epoch
  try {
    await refreshSession()
  } catch {
    if (useAuthStore.getState().epoch === epoch) useAuthStore.getState().clearSession()
  } finally {
    useAuthStore.getState().setReady()
  }
}

// A 401 from these means "wrong credentials", "wrong 2FA code", or "refresh
// rejected", not "session expired" — retrying or redirecting would swallow
// the error the sign-in form needs to display.
const NON_REFRESHABLE = ['/auth/login', '/auth/register', '/auth/refresh', '/auth/2fa/login', '/auth/logout']

apiClient.interceptors.response.use(
  (response) => {
    const config = response.config as SessionRequest
    if (config._sessionEpoch !== useAuthStore.getState().epoch &&
        !NON_REFRESHABLE.some((path) => config.url?.includes(path))) {
      throw new CanceledError('Session changed')
    }
    return response
  },
  async (error: AxiosError) => {
    const original = error.config as SessionRequest
    const url = original?.url ?? ''

    if (error.response?.status !== 401 || !original) return Promise.reject(error)
    if (NON_REFRESHABLE.some((p) => url.includes(p))) return Promise.reject(error)
    if (original._sessionEpoch !== useAuthStore.getState().epoch) return Promise.reject(new CanceledError('Session changed'))

    const detail = (error.response.data as { detail?: { code?: string } } | undefined)?.detail
    if (detail?.code === 'incorrect_current_password') {
      return Promise.reject(error)
    }

    // Refresh once per request; a genuinely revoked session must not loop.
    if (original._retried) {
      toLogin()
      return Promise.reject(error)
    }

    original._retried = true
    try {
      const accessToken = await refreshSession()
      original.headers.Authorization = `Bearer ${accessToken}`
      return apiClient(original)
    } catch (refreshError) {
      if (original._sessionEpoch === useAuthStore.getState().epoch && !axios.isCancel(refreshError)) toLogin()
      return Promise.reject(refreshError)
    }
  }
)

export default apiClient
