'use client'
import { useEffect, useState } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { initObservability } from '@/lib/observability'
import { bootstrapSession, listenForSessionChanges } from '@/lib/api/client'
import { registerPrivateCache } from '@/lib/private-state'
import { useAuthStore } from '@/lib/stores/auth-store'

export function Providers({ children }: { children: React.ReactNode }) {
  // Initialise analytics/error reporting once on the client (no-op without keys).
  useEffect(() => {
    initObservability()
  }, [])

  // Restore the session once per page load. The access token is memory-only
  // now, so a reload starts with nothing until the HttpOnly refresh cookie is
  // exchanged for a fresh one. Failure is just "signed out" and needs no
  // handling here — the middleware and the API both already cover that case.
  useEffect(() => {
    void bootstrapSession()
    return listenForSessionChanges()
  }, [])

  const userId = useAuthStore((state) => state.user?.id)
  // Remount private component state and the query cache when identity changes.
  return <AccountQueries key={userId ?? 'signed-out'}>{children}</AccountQueries>
}

function AccountQueries({ children }: { children: React.ReactNode }) {
  const [client] = useState(() => new QueryClient({
    defaultOptions: {
      queries: { staleTime: 30_000, retry: 1, refetchOnWindowFocus: false },
    },
  }))
  useEffect(() => registerPrivateCache(client), [client])
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>
}
