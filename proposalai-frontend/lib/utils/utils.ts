import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

/**
 * The 'cn' (Class Name) utility:
 * 
 * 1. Merges conditional classes (via clsx)
 *    Example: cn("base-btn", isActive && "bg-blue-500")
 * 
 * 2. Resolves Tailwind class conflicts (via tailwind-merge)
 *    Example: If a component has "p-4" but you pass "p-8" as a prop, 
 *    this ensures "p-8" actually wins instead of both being applied.
 */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/**
 * Formatter for currency (Used in the 'Past Performance' and 'Financial' sections)
 */
export const formatCurrency = (value: number) => {
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
  }).format(value);
};

/**
 * Formatter for dates (Used for Solicitation Deadlines)
 */
export const formatDate = (date: string | Date) => {
  return new Intl.DateTimeFormat('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  }).format(new Date(date));
};