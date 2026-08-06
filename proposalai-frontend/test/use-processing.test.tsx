/**
 * The ingestion progress stream.
 *
 * Two separate bugs have shipped here, and both presented to users as "the
 * server died" during work that went on to succeed:
 *
 *  1. Every `EventSource` error was treated as fatal, including the routine
 *     reconnect the browser performs after the server closes a stream — which
 *     it does on purpose, at its poll budget.
 *  2. The stream is now authorised by a *single-use* ticket, so the browser's
 *     own automatic retry replays a spent credential and is rejected every
 *     time. Reconnection therefore has to mint a fresh ticket, which means the
 *     hook owns it rather than EventSource.
 *
 * These are exactly the paths a manual pass never covers, because reproducing
 * them means waiting minutes for a real ingestion to hit its budget.
 */
import { renderHook, waitFor, act } from '@testing-library/react'
import { setupServer } from 'msw/node'
import { http, HttpResponse } from 'msw'
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'

import { MockEventSource } from './setup'

const API = 'http://api.test'
const PROPOSAL = '11111111-1111-1111-1111-111111111111'

let ticketCalls = 0
let ticketShouldFail = false

const server = setupServer(
  http.post(`${API}/proposals/:id/pipeline/ticket`, () => {
    ticketCalls += 1
    if (ticketShouldFail) {
      return HttpResponse.json({ detail: 'nope' }, { status: 503 })
    }
    return HttpResponse.json({ ticket: `ticket-${ticketCalls}`, expiresInSeconds: 30 })
  })
)

beforeAll(() => server.listen({ onUnhandledRequest: 'error' }))
afterAll(() => server.close())

beforeEach(() => {
  ticketCalls = 0
  ticketShouldFail = false
  MockEventSource.reset()
  vi.stubGlobal('EventSource', MockEventSource)
})
afterEach(() => {
  server.resetHandlers()
  vi.unstubAllGlobals()
  vi.useRealTimers()
})

async function loadHook() {
  const mod = await import('@/lib/hooks')
  return mod.useProcessing
}

function frame(status: string) {
  return {
    proposalId: PROPOSAL,
    status,
    currentStep: 'extract',
    overallProgress: status === 'completed' ? 100 : 40,
    steps: [],
    startedAt: '',
    statusMessage: '',
  }
}

describe('authorisation', () => {
  it('mints a ticket and puts it in the stream URL, never the access token', async () => {
    const useProcessing = await loadHook()
    renderHook(() => useProcessing(PROPOSAL))

    await waitFor(() => expect(MockEventSource.last).toBeTruthy())

    const url = MockEventSource.last.url
    expect(url).toContain('ticket=ticket-1')
    // The whole point of §2.2: no bearer credential in a URL that lands in
    // access logs, browser history and Referer headers.
    expect(url).not.toContain('token=')
  })

  it.each(['', 'undefined', 'null'])(
    'does not open a stream before the id is known (%j)',
    async (id) => {
      // Next's dynamic params arrive as strings, so a missing one shows up as
      // the literal "undefined" rather than a falsy value. Streaming against
      // /proposals/undefined/... would 422 on every poll.
      const useProcessing = await loadHook()
      renderHook(() => useProcessing(id))

      await new Promise((r) => setTimeout(r, 20))
      expect(ticketCalls).toBe(0)
      expect(MockEventSource.instances).toHaveLength(0)
    }
  )
})

describe('frames', () => {
  it('surfaces progress and fires onComplete once terminal', async () => {
    const useProcessing = await loadHook()
    const onComplete = vi.fn()
    const { result } = renderHook(() => useProcessing(PROPOSAL, onComplete))

    await waitFor(() => expect(MockEventSource.last).toBeTruthy())
    act(() => MockEventSource.last.emit(frame('running')))
    expect(result.current.pipeline.status).toBe('running')

    act(() => MockEventSource.last.emit(frame('completed')))
    await waitFor(() => expect(onComplete).toHaveBeenCalledTimes(1))
    expect(MockEventSource.last.closed).toBe(true)
  })

  it('survives a malformed frame', async () => {
    const useProcessing = await loadHook()
    const { result } = renderHook(() => useProcessing(PROPOSAL))

    await waitFor(() => expect(MockEventSource.last).toBeTruthy())
    act(() => MockEventSource.last.onmessage?.({ data: 'not json{' }))

    expect(result.current.connectionError).toBe(false)
    expect(MockEventSource.last.closed).toBe(false)
  })
})

describe('reconnection', () => {
  it('mints a NEW ticket on reconnect, because the old one is spent', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    const useProcessing = await loadHook()
    renderHook(() => useProcessing(PROPOSAL))

    await vi.waitFor(() => expect(MockEventSource.last).toBeTruthy())
    expect(ticketCalls).toBe(1)

    act(() => MockEventSource.last.fail())
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3100)
    })

    await vi.waitFor(() => expect(ticketCalls).toBe(2))
    expect(MockEventSource.last.url).toContain('ticket-2')
  })

  it('does not report a dropped connection while retries remain', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    const useProcessing = await loadHook()
    const { result } = renderHook(() => useProcessing(PROPOSAL))

    await vi.waitFor(() => expect(MockEventSource.last).toBeTruthy())
    act(() => MockEventSource.last.fail())

    // This is bug #1: an error mid-ingestion used to strand the page on an
    // error screen for work that was still running.
    expect(result.current.connectionError).toBe(false)
  })

  it('gives up after the retry budget and says so', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    const useProcessing = await loadHook()
    const { result } = renderHook(() => useProcessing(PROPOSAL))

    await vi.waitFor(() => expect(MockEventSource.last).toBeTruthy())

    // MAX_RECONNECTS is 5, so the sixth failure is fatal.
    for (let i = 0; i < 6; i += 1) {
      act(() => MockEventSource.last?.fail())
      await act(async () => {
        await vi.advanceTimersByTimeAsync(3100)
      })
    }

    await vi.waitFor(() => expect(result.current.connectionError).toBe(true))
  })

  it('resets the budget when a frame arrives', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    const useProcessing = await loadHook()
    const { result } = renderHook(() => useProcessing(PROPOSAL))

    await vi.waitFor(() => expect(MockEventSource.last).toBeTruthy())

    // Four failures, then a good frame, then four more: a long ingestion that
    // reconnects repeatedly but is demonstrably alive must never be declared
    // dead. Without the reset this trips the budget.
    for (let i = 0; i < 4; i += 1) {
      act(() => MockEventSource.last?.fail())
      await act(async () => { await vi.advanceTimersByTimeAsync(3100) })
    }
    act(() => MockEventSource.last.emit(frame('running')))
    for (let i = 0; i < 4; i += 1) {
      act(() => MockEventSource.last?.fail())
      await act(async () => { await vi.advanceTimersByTimeAsync(3100) })
    }

    expect(result.current.connectionError).toBe(false)
  })

  it('retries when the ticket itself cannot be minted', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    ticketShouldFail = true
    const useProcessing = await loadHook()
    const { result } = renderHook(() => useProcessing(PROPOSAL))

    await vi.waitFor(() => expect(ticketCalls).toBeGreaterThan(0))
    expect(MockEventSource.instances).toHaveLength(0)
    expect(result.current.connectionError).toBe(false) // still trying

    await act(async () => { await vi.advanceTimersByTimeAsync(3100) })
    await vi.waitFor(() => expect(ticketCalls).toBeGreaterThan(1))
  })
})

describe('teardown', () => {
  it('closes the stream and stops retrying when unmounted', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    const useProcessing = await loadHook()
    const { unmount } = renderHook(() => useProcessing(PROPOSAL))

    await vi.waitFor(() => expect(MockEventSource.last).toBeTruthy())
    const es = MockEventSource.last
    const before = ticketCalls

    unmount()
    expect(es.closed).toBe(true)

    await act(async () => { await vi.advanceTimersByTimeAsync(10_000) })
    // A pending retry timer after unmount would reopen a stream for a page that
    // is gone, and keep doing so.
    expect(ticketCalls).toBe(before)
  })
})
