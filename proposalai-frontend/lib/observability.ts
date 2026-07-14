// Client-side analytics + error reporting (Story 5.4).
// Both are env-gated: with no keys configured, these are complete no-ops, so
// the app runs fine in local/dev without any external services.

let initialized = false

export function initObservability() {
  if (initialized || typeof window === 'undefined') return
  initialized = true

  const sentryDsn = process.env.NEXT_PUBLIC_SENTRY_DSN
  if (sentryDsn) {
    void import('@sentry/browser').then((Sentry) => {
      Sentry.init({
        dsn: sentryDsn,
        environment: process.env.NODE_ENV,
        tracesSampleRate: 0.1,
      })
    })
  }

  const posthogKey = process.env.NEXT_PUBLIC_POSTHOG_KEY
  if (posthogKey) {
    void import('posthog-js').then(({ default: posthog }) => {
      posthog.init(posthogKey, {
        api_host: process.env.NEXT_PUBLIC_POSTHOG_HOST || 'https://us.i.posthog.com',
        capture_pageview: true,
      })
    })
  }
}

export function captureException(error: unknown) {
  if (typeof window === 'undefined') return
  if (process.env.NEXT_PUBLIC_SENTRY_DSN) {
    void import('@sentry/browser').then((Sentry) => Sentry.captureException(error))
  }
}
