import * as React from 'react'
import { cn } from '@/lib/utils/cn'
import type { ProposalStatus, ComplianceStatus } from '@/types'

export type BadgeVariant =
  | 'default'
  | 'primary'
  | 'success'
  | 'warning'
  | 'danger'
  | 'info'

interface BadgeProps extends React.HTMLAttributes<HTMLSpanElement> {
  variant?: BadgeVariant
}

const variantStyles: Record<BadgeVariant, string> = {
  default:  'bg-[var(--bg-secondary)] text-[var(--text-secondary)] border-[var(--border-default)]',
  primary:  'bg-primary-50 text-primary-800 border-primary-100',
  success:  'bg-[var(--success-bg)] text-[var(--success-text)] border-[var(--success-border)]',
  warning:  'bg-[var(--warning-bg)] text-[var(--warning-text)] border-[var(--warning-border)]',
  danger:   'bg-[var(--danger-bg)] text-[var(--danger-text)] border-[var(--danger-border)]',
  info:     'bg-[var(--info-bg)] text-[var(--info-text)] border-[var(--info-border)]',
}

export function Badge({ variant = 'default', className, children, ...props }: BadgeProps) {
  return (
    <span
      className={cn(
        'inline-flex items-center px-1.5 py-0.5',
        'text-xs font-medium rounded',
        'border',
        variantStyles[variant],
        className
      )}
      {...props}
    >
      {children}
    </span>
  )
}

// ─── Convenience mappers ──────────────────────────────────────────────────────

export function ProposalStatusBadge({ status }: { status: ProposalStatus }) {
  const map: Record<ProposalStatus, { label: string; variant: BadgeVariant }> = {
    draft:          { label: 'Draft',          variant: 'default' },
    processing:     { label: 'Processing',     variant: 'info' },
    in_progress:    { label: 'In progress',    variant: 'primary' },
    review_needed:  { label: 'Review needed',  variant: 'warning' },
    incomplete:     { label: 'Incomplete',     variant: 'danger' },
    submitted:      { label: 'Submitted',      variant: 'success' },
    archived:       { label: 'Archived',       variant: 'default' },
  }
  const { label, variant } = map[status]
  return <Badge variant={variant}>{label}</Badge>
}

export function ComplianceStatusBadge({ status }: { status: ComplianceStatus }) {
  const map: Record<ComplianceStatus, { label: string; variant: BadgeVariant }> = {
    addressed: { label: 'Addressed', variant: 'success' },
    partial:   { label: 'Partial',   variant: 'warning' },
    missing:   { label: 'Missing',   variant: 'danger' },
    na:        { label: 'N/A',       variant: 'default' },
  }
  const { label, variant } = map[status]
  return <Badge variant={variant}>{label}</Badge>
}