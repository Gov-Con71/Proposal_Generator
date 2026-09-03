'use client'
import { create } from 'zustand'
import type { User, Session } from '@/types'

/**
 * Session state. **No credential in this store is persisted.**
 *
 * It used to `persist` the access *and* refresh tokens into localStorage, which
 * meant any script running on the page — an injected dependency, a stored XSS,
 * a browser extension — could read a 30-day refresh token and mint sessions
 * indefinitely (GAP_ANALYSIS §2.5).
 *
 * Now:
 *   - the refresh token lives in an HttpOnly cookie the backend sets, which no
 *     script can read at all;
 *   - the access token lives here, in memory, and is gone on reload;
 *   - a reload re-bootstraps by POSTing /auth/refresh, which the browser
 *     authorises with the cookie automatically.
 *
 * `user` is deliberately not persisted either. It is not a credential, but
 * rehydrating it would render a signed-in shell before the bootstrap confirms
 * the session is real, which is how you get a UI that flashes someone's name
 * after their account was disabled.
 */
interface AuthState {
  user: User | null
  accessToken: string | null
  isAuthenticated: boolean
  /** False until the first /auth/refresh bootstrap settles, either way. */
  isReady: boolean
  setSession: (session: Session) => void
  clearSession: () => void
  setReady: () => void
  /** Patches the signed-in user in place — e.g. reflecting a 2FA toggle —
   * without a full session refresh. No-ops if nobody is signed in. */
  updateUser: (patch: Partial<User>) => void
}

/**
 * Cookie the Next middleware reads to decide whether to redirect to /login.
 *
 * Explicitly **not** a credential: it holds no token and proves nothing, and
 * the API rejects every request that lacks a valid bearer token regardless of
 * what this says. It exists only so a signed-out visitor gets a redirect
 * instead of a dashboard that flashes and then empties. The middleware runs on
 * the frontend origin and so cannot see the backend's HttpOnly cookie, which
 * is why the routing hint has to be separate from the credential.
 */
const MARKER = 'proposalai-authed'

function setMarker(present: boolean) {
  if (typeof document === 'undefined') return
  document.cookie = present
    ? `${MARKER}=1; path=/; SameSite=Lax`
    : `${MARKER}=; path=/; max-age=0; SameSite=Lax`
}

export const useAuthStore = create<AuthState>()((set, get) => ({
  user: null,
  accessToken: null,
  isAuthenticated: false,
  isReady: false,

  setSession: (session: Session) => {
    setMarker(true)
    set({
      user: session.user,
      accessToken: session.accessToken,
      isAuthenticated: true,
      isReady: true,
    })
  },

  clearSession: () => {
    setMarker(false)
    set({
      user: null,
      accessToken: null,
      isAuthenticated: false,
      isReady: true,
    })
  },

  setReady: () => set({ isReady: true }),

  updateUser: (patch) => {
    const { user } = get()
    if (user) set({ user: { ...user, ...patch } })
  },
}))
