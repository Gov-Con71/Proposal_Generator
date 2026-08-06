import { defineConfig, devices } from '@playwright/test'

/**
 * End-to-end smoke tests.
 *
 * Deliberately narrow: one path through the product that touches every layer
 * the unit tests stub out — real Next build, real API, real Postgres, real
 * cookie handling. The unit suite already covers logic; what this catches is
 * the wiring between them, and above all the **cookie attributes**, which
 * cannot be exercised in jsdom and whose misconfiguration is the specific
 * production failure DEPLOYMENT.md §2 warns about (login works, every
 * subsequent refresh 401s).
 *
 * Requires the stack to be up:
 *
 *     docker compose up -d          # api on :8000
 *     npm run dev                   # app on :3000
 *     npx playwright test
 *
 * It is not part of `npm test` and does not run in the default CI job, because
 * it needs those services. Wire it into a job that provisions them.
 */
export default defineConfig({
  testDir: './e2e',
  // A smoke test that needs retries to pass is not telling you anything.
  retries: 0,
  timeout: 60_000,
  expect: { timeout: 10_000 },
  use: {
    baseURL: process.env.E2E_BASE_URL || 'http://localhost:3000',
    trace: 'retain-on-failure',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
})
