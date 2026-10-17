'use client'

import { useEffect, useState } from 'react'
import { authApi, type PasswordPolicy } from '@/lib/api'
import { passwordChecks } from '@/lib/password-validation'

export function usePasswordPolicy() {
  const [policy, setPolicy] = useState<PasswordPolicy | null>(null)
  useEffect(() => {
    let active = true
    authApi.passwordPolicy().then((value) => {
      if (active) setPolicy(value)
    }).catch(() => { /* The server still validates if guidance cannot load. */ })
    return () => { active = false }
  }, [])
  return policy
}

export function PasswordRequirements({ id, password, policy, registration = false }: {
  id: string; password: string; policy: PasswordPolicy | null; registration?: boolean
}) {
  return (
    <div id={id} className="text-xs text-[var(--text-secondary)] space-y-1">
      <p className="font-medium">Password requirements</p>
      {policy ? <ul className="space-y-1">
        {passwordChecks(password, policy).map(({ label, met }) => (
          <li key={label} className={met ? 'text-success-600' : undefined}>
            <span aria-hidden="true">{met ? '✓' : '○'} </span>
            <span className="sr-only">{met ? 'Met: ' : 'Not yet met: '}</span>{label}
          </li>
        ))}
      </ul> : <p>Choose a long password with a variety of characters. Requirements will be checked when you submit.</p>}
      <p>Use a long, unique passphrase. Avoid common passwords.{registration && ' Avoid including your name or the part of your email before @.'}</p>
      {policy && <p>Some characters, such as emoji, use multiple bytes. Additional checks run when you submit.</p>}
    </div>
  )
}
