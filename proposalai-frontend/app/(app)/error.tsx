'use client'
import { useEffect } from 'react'
import { AlertTriangle, RefreshCw } from 'lucide-react'
import { Button } from '@/components/ui/button'

// Global error boundary for the authenticated app segment (Story 4.5).
export default function AppError({
  error,
  reset,
}: {
  error: Error & { digest?: string }
  reset: () => void
}) {
  useEffect(() => {
    // Surface for observability wiring (Sentry lands in Sprint 5.4).
    console.error('App segment error:', error)
  }, [error])

  return (
    <div className="flex flex-col items-center justify-center min-h-[60vh] px-4 text-center">
      <div className="w-12 h-12 rounded-full bg-danger-50 flex items-center justify-center mb-4">
        <AlertTriangle className="w-6 h-6 text-danger-600" />
      </div>
      <h2 className="text-sm font-medium text-[var(--text-primary)] mb-1">Something went wrong</h2>
      <p className="text-xs text-[var(--text-secondary)] max-w-sm mb-5">
        An unexpected error occurred while loading this view. You can retry, or head back to the dashboard.
      </p>
      <div className="flex items-center gap-2">
        <Button variant="primary" size="sm" icon={<RefreshCw className="w-3.5 h-3.5" />} onClick={() => reset()}>
          Try again
        </Button>
        <Button variant="default" size="sm" onClick={() => (window.location.href = '/dashboard')}>
          Back to dashboard
        </Button>
      </div>
    </div>
  )
}
