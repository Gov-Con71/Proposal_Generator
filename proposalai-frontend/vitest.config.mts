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
    globals: true,
    setupFiles: ['./test/setup.ts'],
    // Unit/integration only. Playwright specs live in e2e/ and are driven by
    // Playwright; running them under jsdom fails in a confusing way.
    include: ['test/**/*.test.{ts,tsx}'],
  },
  resolve: {
    // Mirrors the `@/*` alias in tsconfig.json; without it every import in the
    // code under test fails to resolve.
    alias: { '@': root },
  },
})
