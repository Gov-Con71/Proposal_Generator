'use client'
import { useEffect, useState } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { initObservability } from '@/lib/observability'
import { bootstrapSession } from '@/lib/api/client'

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
  }, [])

  // One client per browser session; keep server data reasonably fresh.
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: { staleTime: 30_000, retry: 1, refetchOnWindowFocus: false },
        },
      })
  )
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>
}
