import axios, { AxiosError, type InternalAxiosRequestConfig } from 'axios'
import { useAuthStore } from '@/lib/stores/auth-store'

const BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

export const apiClient = axios.create({
  baseURL: BASE_URL,
  headers: { 'Content-Type': 'application/json' },
  timeout: 30000,
})

// Attach auth token to every request
apiClient.interceptors.request.use((config) => {
  const token = useAuthStore.getState().accessToken
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

function toLogin() {
  useAuthStore.getState().clearSession()
  document.cookie = 'proposalai-token=; path=/; expires=Thu, 01 Jan 1970 00:00:00 GMT'
  window.location.href = '/login'
}

// Refresh tokens rotate, so two concurrent 401s must not both spend the stored
// token — the second would be treated as a replay and revoke every session.
// Share one in-flight refresh between all waiters instead.
let refreshInFlight: Promise<string> | null = null

function refreshSession(): Promise<string> {
  if (refreshInFlight) return refreshInFlight

  const refreshToken = useAuthStore.getState().refreshToken
  if (!refreshToken) return Promise.reject(new Error('No refresh token'))

  refreshInFlight = axios
    // A bare client: apiClient would re-enter this interceptor on failure.
    .post(`${BASE_URL}/auth/refresh`, { refreshToken })
    .then((r) => {
      const session = r.data
      useAuthStore.getState().setSession(session)
      document.cookie = `proposalai-token=${session.accessToken}; path=/`
      return session.accessToken as string
    })
    .finally(() => {
      refreshInFlight = null
    })

  return refreshInFlight
}

// A 401 from these means "wrong credentials" or "refresh rejected", not
// "session expired" — retrying or redirecting would swallow the error the
// sign-in form needs to display.
const NON_REFRESHABLE = ['/auth/login', '/auth/register', '/auth/refresh']

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
