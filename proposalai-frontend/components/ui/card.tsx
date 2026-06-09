import * as React from 'react'
import { cn } from '@/lib/utils/cn'
import type { ComplianceStatus } from '@/types'

// ─── Card ─────────────────────────────────────────────────────────────────────
interface CardProps extends React.HTMLAttributes<HTMLDivElement> {
  padding?: 'none' | 'sm' | 'md'
}

export function Card({ padding = 'md', className, children, ...props }: CardProps) {
  return (
    <div
      className={cn(
        'bg-[var(--bg-primary)]',
        'border border-[var(--border-subtle)]',
        'rounded-xl',
        padding === 'none' && 'p-0',
        padding === 'sm'  && 'p-3',
        padding === 'md'  && 'p-4',
        className
      )}
      {...props}
    >
      {children}
    </div>
  )
}

interface CardHeaderProps extends React.HTMLAttributes<HTMLDivElement> {
  title: string
  subtitle?: string
  action?: React.ReactNode
}

export function CardHeader({ title, subtitle, action, className, ...props }: CardHeaderProps) {
  return (
    <div className={cn('flex items-center justify-between mb-3', className)} {...props}>
      <div>
        <h3 className="text-sm font-medium text-[var(--text-primary)]">{title}</h3>
        {subtitle && (
          <p className="text-xs text-[var(--text-tertiary)] mt-0.5">{subtitle}</p>
        )}
      </div>
      {action && <div className="flex items-center gap-2">{action}</div>}
    </div>
  )
}

// ─── Status dot ───────────────────────────────────────────────────────────────
const dotColors: Record<ComplianceStatus, string> = {
  addressed: 'bg-success-400',
  partial:   'bg-warning-400',
  missing:   'bg-danger-400',
  na:        'bg-neutral-400',
}

interface StatusDotProps {
  status: ComplianceStatus
  className?: string
}

export function StatusDot({ status, className }: StatusDotProps) {
  return (
    <span
      className={cn('inline-block w-[7px] h-[7px] rounded-full shrink-0', dotColors[status], className)}
      aria-label={status}
    />
  )
}

// ─── Progress bar ─────────────────────────────────────────────────────────────
interface ProgressBarProps {
  value: number
  max?: number
  className?: string
  showLabel?: boolean
  colorByValue?: boolean
}

export function ProgressBar({
  value,
  max = 100,
  className,
  showLabel = false,
  colorByValue = true,
}: ProgressBarProps) {
  const pct = Math.min(Math.max((value / max) * 100, 0), 100)

  const fillColor = colorByValue
    ? pct >= 90 ? 'bg-success-400'
    : pct >= 70 ? 'bg-primary-600'
    : pct >= 45 ? 'bg-warning-400'
    : 'bg-danger-400'
    : 'bg-primary-600'

  return (
    <div className={cn('flex items-center gap-2', className)}>
      <div className="flex-1 h-1 bg-[var(--bg-secondary)] rounded-full overflow-hidden">
        <div
          className={cn('h-full rounded-full transition-all duration-300', fillColor)}
          style={{ width: `${pct}%` }}
        />
      </div>
      {showLabel && (
        <span className="text-xs text-[var(--text-secondary)] w-8 text-right shrink-0">
          {Math.round(pct)}%
        </span>
      )}
    </div>
  )
}

// ─── Step indicator ───────────────────────────────────────────────────────────
export interface Step {
  label: string
  status: 'pending' | 'active' | 'done'
}

interface StepIndicatorProps {
  steps: Step[]
  className?: string
}

export function StepIndicator({ steps, className }: StepIndicatorProps) {
  return (
    <div className={cn('flex items-center', className)}>
      {steps.map((step, i) => (
        <React.Fragment key={step.label}>
          <div className="flex items-center gap-2">
            {/* Circle */}
            <div
              className={cn(
                'w-5 h-5 rounded-full border flex items-center justify-center shrink-0',
                'text-[10px] font-medium transition-colors',
                step.status === 'done'   && 'bg-success-50 border-success-400 text-success-600',
                step.status === 'active' && 'bg-primary-50 border-primary-600 text-primary-600',
                step.status === 'pending'&& 'bg-[var(--bg-secondary)] border-[var(--border-default)] text-[var(--text-tertiary)]',
              )}
            >
              {step.status === 'done' ? (
                <svg width="10" height="10" viewBox="0 0 10 10" fill="none">
                  <path d="M2 5l2.5 2.5L8 3" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
                </svg>
              ) : (
                i + 1
              )}
            </div>
            {/* Label */}
            <span
              className={cn(
                'text-xs transition-colors',
                step.status === 'active'  && 'text-primary-600 font-medium',
                step.status === 'done'    && 'text-success-600',
                step.status === 'pending' && 'text-[var(--text-tertiary)]',
              )}
            >
              {step.label}
            </span>
          </div>
          {/* Connector line */}
          {i < steps.length - 1 && (
            <div
              className={cn(
                'flex-1 h-px mx-2 transition-colors',
                steps[i + 1].status !== 'pending'
                  ? 'bg-primary-600'
                  : 'bg-[var(--border-subtle)]'
              )}
            />
          )}
        </React.Fragment>
      ))}
    </div>
  )
}

// ─── Skeleton ─────────────────────────────────────────────────────────────────
interface SkeletonProps extends React.HTMLAttributes<HTMLDivElement> {
  width?: string | number
  height?: string | number
}

export function Skeleton({ width, height, className, style, ...props }: SkeletonProps) {
  return (
    <div
      className={cn('skeleton rounded-md', className)}
      style={{ width, height, ...style }}
      aria-hidden="true"
      {...props}
    />
  )
}