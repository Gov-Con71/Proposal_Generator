'use client'
import { useEffect, useState } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { initObservability } from '@/lib/observability'

export function Providers({ children }: { children: React.ReactNode }) {
  // Initialise analytics/error reporting once on the client (no-op without keys).
  useEffect(() => {
    initObservability()
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
