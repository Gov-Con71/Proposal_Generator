'use client'
import { useState } from 'react'
import Link from 'next/link'
import { ShieldCheck, ArrowLeft } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input, Textarea } from '@/components/ui/input'

export default function RequestAccessPage() {
  const [submitted, setSubmitted] = useState(false)

  if (submitted) {
    return (
      <div className="min-h-screen bg-[var(--bg-secondary)] flex items-center justify-center p-4">
        <div className="w-full max-w-sm bg-[var(--bg-primary)] border border-[var(--border-subtle)] rounded-2xl p-8 text-center animate-fade-in">
          <div className="w-10 h-10 rounded-full bg-success-50 flex items-center justify-center mx-auto mb-4">
            <svg className="w-5 h-5 text-success-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
            </svg>
          </div>
          <h2 className="text-sm font-medium mb-2">Request submitted</h2>
          <p className="text-xs text-[var(--text-secondary)] mb-5">
            Your access request has been sent to the platform administrator. You'll receive an email within 1–2 business days.
          </p>
          <Link href="/login" className="text-xs text-primary-600 hover:text-primary-800 transition-colors">
            ← Back to sign in
          </Link>
        </div>
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-[var(--bg-secondary)] flex items-center justify-center p-4">
      <div className="w-full max-w-sm bg-[var(--bg-primary)] border border-[var(--border-subtle)] rounded-2xl p-8 animate-fade-in">
        <div className="flex items-center gap-2.5 mb-6">
          <div className="w-8 h-8 rounded-lg bg-primary-600 flex items-center justify-center">
            <ShieldCheck className="w-4 h-4 text-white" />
          </div>
          <span className="text-base font-medium">ProposalAI</span>
        </div>

        <h1 className="text-md font-medium mb-1">Request access</h1>
        <p className="text-xs text-[var(--text-tertiary)] mb-5">
          Access is granted by your organization administrator.
        </p>

        <div className="flex flex-col gap-3 mb-5">
          <Input label="Full name"         type="text"  placeholder="Jane Smith" />
          <Input label="Work email"        type="email" placeholder="jane@company.gov" />
          <Input label="Organization"      type="text"  placeholder="Acro Inc." />
          <Textarea label="Why do you need access?" placeholder="Brief description of your role and use case..." rows={3} />
        </div>

        <Button variant="primary" size="lg" className="w-full mb-3" onClick={() => setSubmitted(true)}>
          Submit request
        </Button>

        <Link href="/login" className="flex items-center justify-center gap-1.5 text-xs text-[var(--text-secondary)] hover:text-[var(--text-primary)] transition-colors">
          <ArrowLeft className="w-3.5 h-3.5" /> Back to sign in
        </Link>
      </div>
    </div>
  )
}