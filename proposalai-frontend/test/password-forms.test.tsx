import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import RequestAccessPage from '@/app/(auth)/request-access/page'
import SecurityPage from '@/app/(app)/security/page'
import { authApi } from '@/lib/api'
import { useAuthStore } from '@/lib/stores/auth-store'
import { authError, passwordError } from '@/lib/password-validation'

const { push } = vi.hoisted(() => ({ push: vi.fn() }))
vi.mock('next/navigation', () => ({ useRouter: () => ({ push }) }))
vi.mock('@/lib/api', () => ({ authApi: { passwordPolicy: vi.fn(), register: vi.fn(), changePassword: vi.fn() } }))
vi.mock('@/lib/hooks', () => ({ useActiveSessions: () => ({ data: [], isLoading: false }) }))
const policy = { minLength: 12, maxBytes: 72, minDistinctCharacters: 5 }
const valid = 'trombone-marmalade-97'
const failure = (detail: unknown, status = 422) => ({ response: { status, data: { detail } } })

beforeEach(() => {
  vi.mocked(authApi.passwordPolicy).mockReset().mockResolvedValue(policy)
  vi.mocked(authApi.register).mockReset()
  vi.mocked(authApi.changePassword).mockReset()
  useAuthStore.setState({ user: null, accessToken: null, isAuthenticated: false })
})

async function registration(password = valid) {
  render(<RequestAccessPage />)
  await screen.findByText('At least 12 characters')
  fireEvent.change(screen.getByLabelText('Full name'), { target: { value: 'Jane Smith' } })
  fireEvent.change(screen.getByLabelText('Work email'), { target: { value: 'jane@example.com' } })
  fireEvent.change(screen.getByLabelText('Password'), { target: { value: password } })
}
async function security() {
  render(<SecurityPage />)
  await screen.findByText('At least 12 characters')
  fireEvent.change(screen.getByLabelText('Current password'), { target: { value: 'old-password' } })
  fireEvent.change(screen.getByLabelText('New password'), { target: { value: valid } })
  fireEvent.change(screen.getByLabelText('Confirm password'), { target: { value: valid } })
}

describe('password requirements', () => {
  it('matches character and byte boundaries, whitespace, and distinctness', () => {
    expect(passwordError('abcdefghijk', policy)).toContain('at least 12')
    expect(passwordError('abcdefghijkl', policy)).toBe('')
    expect(passwordError('abcd' + '🙂'.repeat(8), policy)).toBe('')
    expect(passwordError('abcd' + '🙂'.repeat(17), policy)).toBe('')
    expect(passwordError('abcde' + '🙂'.repeat(17), policy)).toContain('72 bytes')
    expect(passwordError('abcdabcdabcd', policy)).toContain('5 different')
    expect(passwordError(' abcdefghijkl', policy)).toContain('spaces')
    expect(passwordError('abcdefghijkl\u0085', policy)).toContain('spaces')
    expect(passwordError('abcdefghijkl\ufeff', policy)).toBe('')
  })
  it('uses configured limits and updates accessible live indicators', async () => {
    vi.mocked(authApi.passwordPolicy).mockResolvedValue({ ...policy, minLength: 16 })
    render(<RequestAccessPage />)
    const row = await screen.findByText('At least 16 characters', { exact: false })
    expect(row).toHaveTextContent('Not yet met:')
    fireEvent.change(screen.getByLabelText('Password'), { target: { value: valid } })
    expect(row).toHaveTextContent('Met:')
    expect(screen.getByLabelText('Password')).toHaveAccessibleDescription(/Password requirements/)
  })
})

describe('registration', () => {
  it('focuses and explains an invalid password before any request', async () => {
    await registration('short')
    fireEvent.click(screen.getByRole('button', { name: 'Create account' }))
    expect(authApi.register).not.toHaveBeenCalled()
    expect(screen.getByRole('alert')).toHaveTextContent('at least 12 characters')
    expect(screen.getByLabelText('Password')).toHaveFocus()
    expect(screen.getByLabelText('Password')).toHaveAttribute('aria-invalid', 'true')
    fireEvent.change(screen.getByLabelText('Password'), { target: { value: valid } })
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })
  it.each([
    ['Password must not contain your name.', 'Password must not contain your name.'],
    ['Choose something unrelated to common words.', 'Choose something unrelated to common words.'],
    [[{ loc: ['body', 'password'], msg: 'Password is too short.' }], 'Password is too short.'],
  ])('shows backend password errors: %s', async (detail, message) => {
    vi.mocked(authApi.register).mockRejectedValue(failure(detail))
    await registration()
    fireEvent.click(screen.getByRole('button', { name: 'Create account' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(message)
    expect(screen.getByLabelText('Password')).toHaveFocus()
    expect(push).not.toHaveBeenCalled()
  })
  it.each([
    [failure('Duplicate', 409), 'An account with that email already exists.'],
    [new Error('Network'), 'Could not create your account. Please try again.'],
    [failure([{ loc: ['body', 'email'], msg: 'Invalid email.' }]), 'Invalid email.'],
  ])('shows non-password failures safely', async (error, message) => {
    vi.mocked(authApi.register).mockRejectedValue(error)
    await registration()
    fireEvent.click(screen.getByRole('button', { name: 'Create account' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(message)
  })
  it('allows server validation when policy is unavailable and redirects on success', async () => {
    vi.mocked(authApi.passwordPolicy).mockRejectedValue(new Error('Offline'))
    vi.mocked(authApi.register).mockResolvedValue({ user: { id: 'u1' }, accessToken: 'token', expiresAt: '' } as never)
    render(<RequestAccessPage />)
    fireEvent.change(screen.getByLabelText('Full name'), { target: { value: 'Jane Smith' } })
    fireEvent.change(screen.getByLabelText('Work email'), { target: { value: 'jane@example.com' } })
    await userEvent.type(screen.getByLabelText('Password'), `${valid}{enter}`)
    await waitFor(() => expect(push).toHaveBeenCalledWith('/dashboard'))
    expect(useAuthStore.getState().accessToken).toBe('token')
  })
})

describe('change password', () => {
  it('explains empty fields and confirmation mismatch', async () => {
    render(<SecurityPage />)
    await screen.findByText('At least 12 characters')
    fireEvent.click(screen.getByRole('button', { name: 'Update password' }))
    expect(screen.getByLabelText('Current password')).toHaveFocus()
    expect(authApi.changePassword).not.toHaveBeenCalled()
    fireEvent.change(screen.getByLabelText('Current password'), { target: { value: 'old' } })
    fireEvent.change(screen.getByLabelText('New password'), { target: { value: valid } })
    fireEvent.change(screen.getByLabelText('Confirm password'), { target: { value: 'different' } })
    fireEvent.click(screen.getByRole('button', { name: 'Update password' }))
    expect(screen.getByRole('alert')).toHaveTextContent('do not match')
    expect(screen.getByLabelText('Confirm password')).toHaveFocus()
  })
  it.each([
    [failure({ code: 'incorrect_current_password', message: 'Your current password is incorrect.' }, 401), 'Current password', 'Your current password is incorrect.'],
    [failure('Choose a less common password.'), 'New password', 'Choose a less common password.'],
  ])('keeps rejected submissions on the form', async (error, field, message) => {
    vi.mocked(authApi.changePassword).mockRejectedValue(error)
    await security()
    fireEvent.click(screen.getByRole('button', { name: 'Update password' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(message)
    expect(screen.getByLabelText(field)).toHaveFocus()
    expect(push).not.toHaveBeenCalled()
  })
  it('supports Enter and clears the session after a successful change', async () => {
    vi.mocked(authApi.changePassword).mockResolvedValue({ message: 'Updated' })
    useAuthStore.setState({ accessToken: 'token', isAuthenticated: true })
    await security()
    await userEvent.type(screen.getByLabelText('Confirm password'), '{enter}')
    await waitFor(() => expect(push).toHaveBeenCalledWith('/login?changed=1'))
    expect(useAuthStore.getState().isAuthenticated).toBe(false)
  })
})

it('falls back safely for malformed API details', () => {
  for (const detail of [null, {}, [null], 5]) expect(authError(failure(detail), 'Fallback').message).toBe('Fallback')
})
