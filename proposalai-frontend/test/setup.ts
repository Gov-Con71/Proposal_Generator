import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterEach, beforeEach, vi } from 'vitest'

// Node 25+ exposes a native storage getter even when no storage file is
// configured. Vitest 2 preserves that global instead of copying jsdom's.
// Vitest exposes the underlying jsdom instance; window itself aliases the
// test global, so use the instance to reach the browser's Storage objects.
declare const jsdom: { window: Window }
Object.defineProperty(globalThis, 'localStorage', { configurable: true, value: jsdom.window.localStorage })
Object.defineProperty(globalThis, 'sessionStorage', { configurable: true, value: jsdom.window.sessionStorage })

// The API base the code reads at module load.
process.env.NEXT_PUBLIC_API_URL = 'http://api.test'

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

beforeEach(() => {
  // Cookies persist across tests in jsdom, and the auth store writes a marker
  // cookie — without this a signed-in test leaks into the next one.
  document.cookie.split(';').forEach((c) => {
    const name = c.split('=')[0].trim()
    if (name) document.cookie = `${name}=; path=/; max-age=0`
  })
})

/**
 * jsdom has no EventSource, and the progress stream is one of the two things
 * most worth testing here. This is a controllable stand-in: tests drive it by
 * emitting frames or errors, and assert on what the hook does in response.
 */
export class MockEventSource {
  static instances: MockEventSource[] = []
  static readonly CONNECTING = 0
  static readonly OPEN = 1
  static readonly CLOSED = 2

  onmessage: ((e: { data: string }) => void) | null = null
  onerror: (() => void) | null = null
  readyState = MockEventSource.CONNECTING
  closed = false

  constructor(public url: string) {
    MockEventSource.instances.push(this)
    this.readyState = MockEventSource.OPEN
  }

  emit(payload: unknown) {
    this.onmessage?.({ data: JSON.stringify(payload) })
  }

  fail() {
    this.readyState = MockEventSource.CLOSED
    this.onerror?.()
  }

  close() {
    this.closed = true
    this.readyState = MockEventSource.CLOSED
  }

  static reset() {
    MockEventSource.instances = []
  }

  static get last() {
    return MockEventSource.instances[MockEventSource.instances.length - 1]
  }
}
