import * as React from 'react'
import { Slot } from '@radix-ui/react-slot'
import { cn } from '@/lib/utils/cn'

export type ButtonVariant = 'primary' | 'default' | 'ghost' | 'danger' | 'success'
export type ButtonSize = 'sm' | 'md' | 'lg'

export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant
  size?: ButtonSize
  loading?: boolean
  icon?: React.ReactNode
  iconPosition?: 'left' | 'right'
  asChild?: boolean
}

const variantStyles: Record<ButtonVariant, string> = {
  primary: [
    'bg-primary-600 text-white',
    'border-primary-600',
    'hover:bg-primary-800 hover:border-primary-800',
    'active:scale-[0.98]',
    'disabled:bg-primary-100 disabled:border-primary-100 disabled:text-primary-400',
  ].join(' '),

  default: [
    'bg-[var(--bg-primary)] text-[var(--text-primary)]',
    'border-[var(--border-default)]',
    'hover:bg-[var(--bg-secondary)]',
    'active:scale-[0.98]',
    'disabled:opacity-50',
  ].join(' '),

  ghost: [
    'bg-transparent text-[var(--text-secondary)]',
    'border-transparent',
    'hover:bg-[var(--bg-secondary)] hover:text-[var(--text-primary)]',
    'active:scale-[0.98]',
    'disabled:opacity-50',
  ].join(' '),

  danger: [
    'bg-danger-600 text-white',
    'border-danger-600',
    'hover:bg-danger-800 hover:border-danger-800',
    'active:scale-[0.98]',
    'disabled:opacity-50',
  ].join(' '),

  success: [
    'bg-success-600 text-white',
    'border-success-600',
    'hover:bg-success-800 hover:border-success-800',
    'active:scale-[0.98]',
    'disabled:opacity-50',
  ].join(' '),
}

const sizeStyles: Record<ButtonSize, string> = {
  sm: 'h-7 px-3 text-xs gap-1.5 rounded',
  md: 'h-8 px-3.5 text-sm gap-2 rounded-md',
  lg: 'h-9 px-4 text-base gap-2 rounded-md',
}

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  (
    {
      variant = 'default',
      size = 'md',
      loading = false,
      icon,
      iconPosition = 'left',
      className,
      children,
      disabled,
      asChild = false,
      ...props
    },
    ref
  ) => {
    const isDisabled = disabled || loading
    const Comp = asChild ? Slot : 'button'

    return (
      <Comp
        ref={ref}
        disabled={isDisabled}
        className={cn(
          // Base
          'inline-flex items-center justify-center',
          'border font-medium',
          'transition-all duration-100',
          'select-none whitespace-nowrap',
          'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-600 focus-visible:ring-offset-1',
          'disabled:cursor-not-allowed',
          // Variant
          variantStyles[variant],
          // Size
          sizeStyles[size],
          className
        )}
        {...props}
      >
        {loading ? (
          <>
            <LoadingSpinner size={size} />
            {children && <span>{children}</span>}
          </>
        ) : (
          <>
            {icon && iconPosition === 'left' && (
              <span className="shrink-0">{icon}</span>
            )}
            {children}
            {icon && iconPosition === 'right' && (
              <span className="shrink-0">{icon}</span>
            )}
          </>
        )}
      </Comp>
    )
  }
)

Button.displayName = 'Button'

// ─── Loading spinner ──────────────────────────────────────────────────────────
function LoadingSpinner({ size }: { size: ButtonSize }) {
  const spinnerSize = size === 'sm' ? 'w-3 h-3' : 'w-3.5 h-3.5'
  return (
    <svg
      className={cn('animate-spin shrink-0', spinnerSize)}
      xmlns="http://www.w3.org/2000/svg"
      fill="none"
      viewBox="0 0 24 24"
      aria-hidden="true"
    >
      <circle
        className="opacity-25"
        cx="12" cy="12" r="10"
        stroke="currentColor" strokeWidth="4"
      />
      <path
        className="opacity-75"
        fill="currentColor"
        d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
      />
    </svg>
  )
}