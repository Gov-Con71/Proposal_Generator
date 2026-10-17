import { act, render, screen, waitFor } from '@testing-library/react'
import { useQuery, useQueryClient, type QueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { beforeEach, expect, it, vi } from 'vitest'
import { Providers } from '@/app/providers'
import { useAuthStore } from '@/lib/stores/auth-store'

vi.mock('@/lib/api/client', () => ({
  bootstrapSession: vi.fn(),
  listenForSessionChanges: () => () => {},
}))
vi.mock('@/lib/observability', () => ({ initObservability: vi.fn() }))

beforeEach(() => useAuthStore.getState().clearSession())

it('remounts private component state and query caches when accounts change', async () => {
  let cache!: QueryClient
  function Probe() {
    cache = useQueryClient()
    const [owner] = useState(() => useAuthStore.getState().user?.id)
    const { data } = useQuery({ queryKey: ['private'], queryFn: () => 'unused', enabled: false })
    return <p>{owner}:{data ?? 'empty'}</p>
  }
  useAuthStore.getState().setSession({ user: { id: 'u1' }, accessToken: 'first' } as never)
  render(<Providers><Probe /></Providers>)
  act(() => cache.setQueryData(['private'], 'private-first-user-data'))
  await screen.findByText('u1:private-first-user-data')
  const previousCache = cache
  act(() => useAuthStore.getState().setSession({ user: { id: 'u2' }, accessToken: 'second' } as never))
  await waitFor(() => expect(screen.getByText('u2:empty')).toBeInTheDocument())
  expect(cache).not.toBe(previousCache)
  expect(previousCache.getQueryData(['private'])).toBeUndefined()
})
