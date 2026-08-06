/**
 * The drafting trigger and its polling loop.
 *
 * This hook had a genuine correctness bug until recently: it queued drafting
 * per *proposal* but polled the *document* for progress, so a second bid on the
 * same RFP reported itself finished the moment the first one completed. The
 * status moved onto the proposal (migration 0005); these tests hold it there.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderHook, act, waitFor } from '@testing-library/react'
import { setupServer } from 'msw/node'
import { http, HttpResponse } from 'msw'
import React from 'react'
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'

const API = 'http://api.test'
const PROPOSAL = '22222222-2222-2222-2222-222222222222'

let draftCalls: string[] = []
let statuses: string[] = []
let failureReason: string | null = null
let pollCount = 0

const server = setupServer(
  http.post(`${API}/proposals/:id/draft`, ({ params }) => {
    draftCalls.push(params.id as string)
    return HttpResponse.json(
      { proposalId: params.id, rfpId: 'r', draftingStatus: 'drafting', requirementsCount: 3 },
      { status: 202 }
    )
  }),
  http.get(`${API}/proposals/:id`, () => {
    const status = statuses[Math.min(pollCount, statuses.length - 1)]
    pollCount += 1
    return HttpResponse.json({
      id: PROPOSAL,
      draftingStatus: status,
      draftingFailureReason: failureReason,
    })
  })
)

beforeAll(() => server.listen({ onUnhandledRequest: 'error' }))
afterAll(() => server.close())

beforeEach(() => {
  draftCalls = []
  statuses = ['drafted']
  failureReason = null
  pollCount = 0
})
afterEach(() => {
  server.resetHandlers()
  vi.useRealTimers()
})

function wrapper({ children }: { children: React.ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return React.createElement(QueryClientProvider, { client }, children)
}

async function loadHook() {
  const mod = await import('@/lib/hooks')
  return mod.useGenerateDraft
}

it('queues drafting against the proposal and polls the proposal', async () => {
  const useGenerateDraft = await loadHook()
  const { result } = renderHook(() => useGenerateDraft(PROPOSAL), { wrapper })

  await act(async () => {
    await result.current.generate()
  })

  expect(draftCalls).toEqual([PROPOSAL])
  expect(result.current.status).toBe('idle')
  expect(result.current.error).toBeNull()
})

it('surfaces the server-recorded reason for a failed draft', async () => {
  // A generic "Draft generation failed." is the difference between "retry" and
  // "fix your API key" — the §1.1 misdiagnosis in miniature.
  statuses = ['draft_failed']
  failureReason = 'NotFound: model gemini-1.0-pro is not found'
  const useGenerateDraft = await loadHook()
  const { result } = renderHook(() => useGenerateDraft(PROPOSAL), { wrapper })

  await act(async () => {
    await result.current.generate()
  })

  await waitFor(() => expect(result.current.status).toBe('failed'))
  expect(result.current.error).toContain('is not found')
})

it('keeps polling while the draft is still running', async () => {
  statuses = ['drafting', 'drafting', 'drafted']
  vi.useFakeTimers({ shouldAdvanceTime: true })
  const useGenerateDraft = await loadHook()
  const { result } = renderHook(() => useGenerateDraft(PROPOSAL), { wrapper })

  let pending: Promise<void>
  act(() => {
    pending = result.current.generate()
  })
  await act(async () => {
    await vi.advanceTimersByTimeAsync(7000)
    await pending
  })

  expect(pollCount).toBeGreaterThanOrEqual(3)
  expect(result.current.status).toBe('idle')
})

it('refuses to act on an id that is not there yet', async () => {
  const useGenerateDraft = await loadHook()
  const { result } = renderHook(() => useGenerateDraft('undefined'), { wrapper })

  await act(async () => {
    await result.current.generate()
  })

  expect(draftCalls).toEqual([])
})
