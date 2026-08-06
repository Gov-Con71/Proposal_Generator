import { expect, test } from '@playwright/test'

/**
 * Register → land in the app → reload → still signed in → sign out.
 *
 * The reload is the point. The access token lives only in memory, so surviving
 * a reload proves the whole HttpOnly-cookie bootstrap works end to end: the
 * cookie was set with attributes the browser accepted, it was sent back to the
 * API origin, `/auth/refresh` rotated it, and the app re-armed itself from the
 * response. Every one of those steps is invisible to jsdom, and getting the
 * cookie attributes wrong in production produces exactly this symptom — sign-in
 * succeeds, then everything 401s (DEPLOYMENT.md §2).
 */

const API = process.env.E2E_API_URL || 'http://localhost:8000'

function uniqueEmail() {
  return `e2e_${Date.now()}_${Math.floor(Math.random() * 1e4)}@example.com`
}

// Satisfies the password policy and shares no 4+ character run with the email.
const PASSWORD = 'quixotic-lamppost-88'

test('a session survives a reload, and sign-out ends it', async ({ page }) => {
  const email = uniqueEmail()

  await page.goto('/request-access')
  await page.getByLabel(/full name/i).fill('Ada Lovelace')
  await page.getByLabel(/email/i).fill(email)
  await page.getByLabel(/password/i).first().fill(PASSWORD)
  await page.getByRole('button', { name: /create account|request access/i }).click()

  await expect(page).toHaveURL(/\/dashboard/)

  // The credential must be a cookie the page cannot read...
  const cookies = await page.context().cookies()
  const refresh = cookies.find((c) => c.name === 'proposalai_refresh')
  expect(refresh, 'refresh cookie must be set').toBeTruthy()
  expect(refresh!.httpOnly, 'refresh cookie must be HttpOnly').toBe(true)

  // ...and genuinely unreadable from script.
  const visible = await page.evaluate(() => document.cookie)
  expect(visible).not.toContain('proposalai_refresh')

  // ...and no token may be sitting in web storage.
  const stored = await page.evaluate(
    () => JSON.stringify(localStorage) + JSON.stringify(sessionStorage)
  )
  expect(stored).not.toContain('refresh')
  expect(stored.toLowerCase()).not.toContain('bearer')

  // The reload: memory is cleared, so this only works via the cookie.
  await page.reload()
  await expect(page).toHaveURL(/\/dashboard/)
  await expect(page.getByRole('link', { name: /current/i })).toBeVisible()

  // Sign-out must revoke server-side, not merely clear client state.
  await page.getByRole('button', { name: /sign out|log ?out/i }).click()
  await expect(page).toHaveURL(/\/login/)

  const after = await page.context().cookies()
  expect(after.find((c) => c.name === 'proposalai_refresh')?.value || '').toBe('')

  // And the revoked session cannot be resurrected.
  const res = await page.request.post(`${API}/auth/refresh`)
  expect(res.status()).toBe(401)
})

test('a signed-out visitor is redirected away from the app', async ({ page }) => {
  await page.goto('/dashboard')
  await expect(page).toHaveURL(/\/login/)
})
