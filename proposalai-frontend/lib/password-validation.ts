import type { PasswordPolicy } from '@/lib/api'

export function passwordChecks(password: string, policy: PasswordPolicy) {
  const characters = Array.from(password)
  return [
    { label: `At least ${policy.minLength} characters`, met: characters.length >= policy.minLength },
    { label: `At least ${policy.minDistinctCharacters} different characters`, met: new Set(characters).size >= policy.minDistinctCharacters },
    // Python str.strip also recognises these control characters, but not BOM.
    { label: 'No spaces at the beginning or end', met: !!password && !/^[\u0009-\u000d\u001c-\u0020\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]|[\u0009-\u000d\u001c-\u0020\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]$/.test(password) },
    { label: `No more than ${policy.maxBytes} bytes`, met: !!password && new TextEncoder().encode(password).length <= policy.maxBytes },
  ]
}

export function passwordError(password: string, policy: PasswordPolicy | null) {
  if (!password) return 'Enter a password.'
  if (!policy) return ''
  const failed = passwordChecks(password, policy).filter((check) => !check.met)
  return failed.length ? `Password requirements: ${failed.map((check) => check.label.toLowerCase()).join('; ')}.` : ''
}

export function authError(error: unknown, fallback: string): { status?: number; message: string; field?: string; code?: string } {
  const response = (error as { response?: { status?: number; data?: { detail?: unknown } } } | null)?.response
  const detail = response?.data?.detail
  const result = { status: response?.status, message: fallback }
  if (typeof detail === 'string') return { ...result, message: detail || fallback }
  if (Array.isArray(detail)) {
    const issues = detail.filter((item) => item && typeof item.msg === 'string')
    return { ...result, message: issues.map((item) => item.msg).join(' ') || fallback,
      field: Array.isArray(issues[0]?.loc) ? String(issues[0].loc.at(-1)) : undefined }
  }
  if (detail && typeof detail === 'object') {
    const value = detail as { message?: unknown; code?: unknown }
    return { ...result, message: typeof value.message === 'string' ? value.message : fallback,
      code: typeof value.code === 'string' ? value.code : undefined }
  }
  return result
}
