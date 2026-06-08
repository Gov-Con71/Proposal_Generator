import { format, formatDistanceToNow, isValid, parseISO } from 'date-fns'

// ─── Date ────────────────────────────────────────────────────────────────────

/**
 * Format an ISO date string to "Jun 15, 2026"
 */
export function formatDate(date: string | Date): string {
  const d = typeof date === 'string' ? parseISO(date) : date
  if (!isValid(d)) return '—'
  return format(d, 'MMM d, yyyy')
}

/**
 * Format an ISO date string to "Jun 15, 2026 · 9:42 AM"
 */
export function formatDateTime(date: string | Date): string {
  const d = typeof date === 'string' ? parseISO(date) : date
  if (!isValid(d)) return '—'
  return format(d, "MMM d, yyyy · h:mm a")
}

/**
 * "2 hours ago", "3 days ago"
 */
export function formatRelative(date: string | Date): string {
  const d = typeof date === 'string' ? parseISO(date) : date
  if (!isValid(d)) return '—'
  return formatDistanceToNow(d, { addSuffix: true })
}

/**
 * Days remaining until a deadline
 * Returns negative if past due
 */
export function daysUntil(date: string | Date): number {
  const d = typeof date === 'string' ? parseISO(date) : date
  const now = new Date()
  return Math.ceil((d.getTime() - now.getTime()) / (1000 * 60 * 60 * 24))
}

// ─── Currency ────────────────────────────────────────────────────────────────

/**
 * Format a number as USD currency
 * formatCurrency(49907.88) → "$49,907.88"
 */
export function formatCurrency(
  value: number,
  options?: { compact?: boolean }
): string {
  if (options?.compact) {
    if (value >= 1_000_000) return `$${(value / 1_000_000).toFixed(1)}M`
    if (value >= 1_000)     return `$${(value / 1_000).toFixed(0)}K`
  }
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: 0,
    maximumFractionDigits: 2,
  }).format(value)
}

// ─── Percentage ──────────────────────────────────────────────────────────────

/**
 * Format a decimal (0-1) or integer (0-100) as "87%"
 */
export function formatPercent(value: number): string {
  const pct = value <= 1 ? value * 100 : value
  return `${Math.round(pct)}%`
}

// ─── File size ───────────────────────────────────────────────────────────────

/**
 * Format bytes to human-readable file size
 * formatFileSize(2400000) → "2.4 MB"
 */
export function formatFileSize(bytes: number): string {
  if (bytes === 0) return '0 B'
  const k = 1024
  const sizes = ['B', 'KB', 'MB', 'GB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return `${parseFloat((bytes / Math.pow(k, i)).toFixed(1))} ${sizes[i]}`
}

// ─── String ──────────────────────────────────────────────────────────────────

/**
 * Truncate a string with ellipsis
 */
export function truncate(str: string, maxLength: number): string {
  if (str.length <= maxLength) return str
  return `${str.slice(0, maxLength)}…`
}

/**
 * Get initials from a full name
 * getInitials("John Smith") → "JS"
 */
export function getInitials(name: string): string {
  return name
    .split(' ')
    .slice(0, 2)
    .map(n => n[0]?.toUpperCase() ?? '')
    .join('')
}