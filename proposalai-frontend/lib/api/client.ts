import axios, { AxiosError, type InternalAxiosRequestConfig } from 'axios'
import { useAuthStore } from '@/lib/stores/auth-store'

const BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

export const apiClient = axios.create({
  baseURL: BASE_URL,
  headers: { 'Content-Type': 'application/json' },
  timeout: 30000,
  // Required for the HttpOnly refresh cookie to be sent to the API origin.
  // Without it the browser silently omits the cookie and every refresh 401s.
  withCredentials: true,
})

// Attach the in-memory access token to every request.
apiClient.interceptors.request.use((config) => {
  const token = useAuthStore.getState().accessToken
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
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

/**
 * Exchanges the HttpOnly refresh cookie for a new access token.
 *
 * There is no token argument any more: the browser attaches the cookie, and the
 * page cannot read it. That is the point — the credential that survives a
 * reload is one script cannot touch.
 */
export function refreshSession(): Promise<string> {
  if (refreshInFlight) return refreshInFlight

  refreshInFlight = axios
    // A bare client: apiClient would re-enter the response interceptor on 401.
    .post(`${BASE_URL}/auth/refresh`, null, { withCredentials: true })
    .then((r) => {
      useAuthStore.getState().setSession(r.data)
      return r.data.accessToken as string
    })
    .finally(() => {
      refreshInFlight = null
    })

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
  try {
    await refreshSession()
  } catch {
    useAuthStore.getState().clearSession()
  } finally {
    useAuthStore.getState().setReady()
  }
}

// A 401 from these means "wrong credentials", "wrong 2FA code", or "refresh
// rejected", not "session expired" — retrying or redirecting would swallow
// the error the sign-in form needs to display.
const NON_REFRESHABLE = ['/auth/login', '/auth/register', '/auth/refresh', '/auth/2fa/login']

apiClient.interceptors.response.use(
  (response) => response,
  async (error: AxiosError) => {
    const original = error.config as InternalAxiosRequestConfig & { _retried?: boolean }
    const url = original?.url ?? ''

    if (error.response?.status !== 401 || !original) return Promise.reject(error)
    if (NON_REFRESHABLE.some((p) => url.includes(p))) return Promise.reject(error)

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
    } catch {
      toLogin()
      return Promise.reject(error)
    }
  }
)

export default apiClient
