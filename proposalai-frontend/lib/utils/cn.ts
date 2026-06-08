import { clsx, type ClassValue } from 'clsx'
import { twMerge } from 'tailwind-merge'

/**
 * Merge Tailwind classes safely.
 * Resolves conflicts (e.g. bg-red-500 + bg-blue-500 → bg-blue-500)
 * and removes duplicates.
 *
 * Usage:
 *   cn('px-4 py-2', isActive && 'bg-primary-600 text-white', className)
 */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}