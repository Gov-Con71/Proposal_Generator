import * as React from 'react'
import { AlertTriangle, Inbox, RefreshCw } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/card'
import { cn } from '@/lib/utils/cn'

// ─── EmptyState ───────────────────────────────────────────────────────────────
interface EmptyStateProps extends React.HTMLAttributes<HTMLDivElement> {
  title: string
  message?: string
  icon?: React.ReactNode
  action?: React.ReactNode
}

export function EmptyState({ title, message, icon, action, className, ...props }: EmptyStateProps) {
  return (
    <div className={cn('flex flex-col items-center justify-center text-center px-4 py-12', className)} {...props}>
      <div className="w-10 h-10 rounded-full bg-[var(--bg-secondary)] flex items-center justify-center mb-3">
        {icon ?? <Inbox className="w-5 h-5 text-[var(--text-tertiary)]" />}
      </div>
      <p className="text-sm font-medium text-[var(--text-primary)]">{title}</p>
      {message && <p className="text-xs text-[var(--text-secondary)] max-w-sm mt-1">{message}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  )
}

// ─── ErrorState ───────────────────────────────────────────────────────────────
interface ErrorStateProps extends React.HTMLAttributes<HTMLDivElement> {
  title?: string
  error?: unknown
  /** Overrides the message derived from `error` — for failures that aren't exceptions. */
  message?: string
  onRetry?: () => void
}

/** Turns an axios/query rejection into something a user can act on. A dead
 *  backend has no `response`, and that reads very differently from a 4xx. */
export function errorMessage(error: unknown): string {
  const e = error as
    | { response?: { status?: number; data?: { detail?: string } }; code?: string; message?: string }
    | undefined

  if (!e) return 'Something went wrong.'

  const detail = e.response?.data?.detail
  if (detail) return detail

  const status = e.response?.status
  if (status === undefined) {
    // No response at all — the request never reached the API.
    return 'Cannot reach the server. Check that the backend is running, then retry.'
  }
  if (status === 403) return 'You do not have access to this resource.'
  if (status === 404) return 'This resource no longer exists.'
  if (status >= 500) return 'The server failed to handle this request. Please retry.'
  return e.message || 'Something went wrong.'
}

export function ErrorState({ title = 'Could not load this view', error, message, onRetry, className, ...props }: ErrorStateProps) {
  return (
    <div className={cn('flex flex-col items-center justify-center text-center px-4 py-12', className)} {...props}>
      <div className="w-10 h-10 rounded-full bg-danger-50 flex items-center justify-center mb-3">
        <AlertTriangle className="w-5 h-5 text-danger-600" />
      </div>
      <p className="text-sm font-medium text-[var(--text-primary)]">{title}</p>
      <p className="text-xs text-[var(--text-secondary)] max-w-sm mt-1">{message ?? errorMessage(error)}</p>
      {onRetry && (
        <Button
          variant="default"
          size="sm"
          className="mt-4"
          icon={<RefreshCw className="w-3.5 h-3.5" />}
          onClick={onRetry}
        >
          Retry
        </Button>
      )}
    </div>
  )
}

// ─── TableSkeleton ────────────────────────────────────────────────────────────
interface TableSkeletonProps {
  rows?: number
  cols: number
}

export function TableSkeleton({ rows = 5, cols }: TableSkeletonProps) {
  return (
    <>
      {Array.from({ length: rows }).map((_, r) => (
        <tr key={r} className="border-b border-[var(--border-subtle)] last:border-0">
          {Array.from({ length: cols }).map((_, c) => (
            <td key={c} className="px-4 py-3">
              <Skeleton height={12} />
            </td>
          ))}
        </tr>
      ))}
    </>
  )
}
