import * as React from 'react'
import { cn } from '@/lib/utils/cn'

// ─── Input ────────────────────────────────────────────────────────────────────
export interface InputProps extends React.InputHTMLAttributes<HTMLInputElement> {
  label?: string
  hint?: string
  error?: string
}

export const Input = React.forwardRef<HTMLInputElement, InputProps>(
  ({ label, hint, error, className, id, ...props }, ref) => {
    const inputId = id || label?.toLowerCase().replace(/\s+/g, '-')

    return (
      <div className="flex flex-col gap-1">
        {label && (
          <label
            htmlFor={inputId}
            className="text-xs text-[var(--text-secondary)] font-medium"
          >
            {label}
          </label>
        )}
        <input
          ref={ref}
          id={inputId}
          className={cn(
            'h-8 w-full px-2.5',
            'text-sm text-[var(--text-primary)]',
            'bg-[var(--bg-primary)]',
            'border border-[var(--border-default)] rounded-md',
            'placeholder:text-[var(--text-tertiary)]',
            'transition-colors duration-100',
            'hover:border-[var(--border-strong)]',
            'focus:outline-none focus:border-primary-600',
            'disabled:opacity-50 disabled:cursor-not-allowed',
            error && 'border-danger-400 focus:border-danger-600',
            className
          )}
          {...props}
        />
        {error && (
          <p className="text-xs text-danger-600">{error}</p>
        )}
        {hint && !error && (
          <p className="text-xs text-[var(--text-tertiary)]">{hint}</p>
        )}
      </div>
    )
  }
)
Input.displayName = 'Input'

// ─── Textarea ─────────────────────────────────────────────────────────────────
export interface TextareaProps extends React.TextareaHTMLAttributes<HTMLTextAreaElement> {
  label?: string
  hint?: string
  error?: string
}

export const Textarea = React.forwardRef<HTMLTextAreaElement, TextareaProps>(
  ({ label, hint, error, className, id, ...props }, ref) => {
    const inputId = id || label?.toLowerCase().replace(/\s+/g, '-')

    return (
      <div className="flex flex-col gap-1">
        {label && (
          <label
            htmlFor={inputId}
            className="text-xs text-[var(--text-secondary)] font-medium"
          >
            {label}
          </label>
        )}
        <textarea
          ref={ref}
          id={inputId}
          className={cn(
            'w-full px-2.5 py-2',
            'text-sm text-[var(--text-primary)]',
            'bg-[var(--bg-primary)]',
            'border border-[var(--border-default)] rounded-md',
            'placeholder:text-[var(--text-tertiary)]',
            'resize-y min-h-[72px]',
            'transition-colors duration-100',
            'hover:border-[var(--border-strong)]',
            'focus:outline-none focus:border-primary-600',
            'disabled:opacity-50 disabled:cursor-not-allowed',
            error && 'border-danger-400 focus:border-danger-600',
            className
          )}
          {...props}
        />
        {error && (
          <p className="text-xs text-danger-600">{error}</p>
        )}
        {hint && !error && (
          <p className="text-xs text-[var(--text-tertiary)]">{hint}</p>
        )}
      </div>
    )
  }
)
Textarea.displayName = 'Textarea'

// ─── Select ───────────────────────────────────────────────────────────────────
export interface SelectOption {
  value: string
  label: string
}

export interface SelectProps extends React.SelectHTMLAttributes<HTMLSelectElement> {
  label?: string
  hint?: string
  error?: string
  options: SelectOption[]
  placeholder?: string
}

export const Select = React.forwardRef<HTMLSelectElement, SelectProps>(
  ({ label, hint, error, options, placeholder, className, id, ...props }, ref) => {
    const inputId = id || label?.toLowerCase().replace(/\s+/g, '-')

    return (
      <div className="flex flex-col gap-1">
        {label && (
          <label
            htmlFor={inputId}
            className="text-xs text-[var(--text-secondary)] font-medium"
          >
            {label}
          </label>
        )}
        <select
          ref={ref}
          id={inputId}
          className={cn(
            'h-8 w-full px-2.5',
            'text-sm text-[var(--text-primary)]',
            'bg-[var(--bg-primary)]',
            'border border-[var(--border-default)] rounded-md',
            'appearance-none',
            'transition-colors duration-100',
            'hover:border-[var(--border-strong)]',
            'focus:outline-none focus:border-primary-600',
            'disabled:opacity-50 disabled:cursor-not-allowed',
            error && 'border-danger-400',
            className
          )}
          {...props}
        >
          {placeholder && (
            <option value="" disabled>
              {placeholder}
            </option>
          )}
          {options.map((opt) => (
            <option key={opt.value} value={opt.value}>
              {opt.label}
            </option>
          ))}
        </select>
        {error && (
          <p className="text-xs text-danger-600">{error}</p>
        )}
        {hint && !error && (
          <p className="text-xs text-[var(--text-tertiary)]">{hint}</p>
        )}
      </div>
    )
  }
)
Select.displayName = 'Select'