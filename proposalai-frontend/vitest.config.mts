import { defineConfig } from 'vitest/config'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const root = path.dirname(fileURLToPath(import.meta.url))

// No @vitejs/plugin-react: its only job here would be the JSX transform, which
// esbuild already does, and pulling it in makes npm resolve a second copy of
// Vite whose Plugin type is structurally incompatible with the one Vitest
// bundles — `tsc --noEmit` then fails on this file for no runtime reason.
export default defineConfig({
  esbuild: { jsx: 'automatic' },
  test: {
    environment: 'jsdom',
    environmentOptions: { jsdom: { url: 'http://localhost:3000' } },
    globals: true,
    setupFiles: ['./test/setup.ts'],
    // Unit/integration only. Playwright specs live in e2e/ and are driven by
    // Playwright; running them under jsdom fails in a confusing way.
    include: ['test/**/*.test.{ts,tsx}'],
    // Vitest defaults to 5s per test, which is generous for an assertion and
    // tight for what these actually do first: `await import('@/lib/hooks')`
    // cold-compiles the whole hook module graph (axios, zustand, TanStack
    // Query) through Vite, alongside MSW's server and a jsdom render. On a
    // warm machine that is milliseconds; on a cold one — a CI runner, or a
    // laptop straight after `npm ci` — it has been measured past 7s, and the
    // tests that pay that cost fail on time rather than on their assertion.
    // Raised rather than removed: a genuine hang should still fail the run.
    testTimeout: 20_000,
    hookTimeout: 30_000,
  },
  resolve: {
    // Mirrors the `@/*` alias in tsconfig.json; without it every import in the
    // code under test fails to resolve.
    alias: { '@': root },
  },
})
