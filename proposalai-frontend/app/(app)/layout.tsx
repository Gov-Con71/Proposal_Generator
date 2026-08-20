'use client'
import Link from 'next/link'
import { usePathname, useRouter } from 'next/navigation'
import {
  ShieldCheck, LayoutDashboard, PenLine, Table2,
  History, Building2, Users, LogOut, HelpCircle,
  Shield, Bell, Plus, FileText, Calculator, Archive
} from 'lucide-react'
import { cn } from '@/lib/utils/cn'
import { Button } from '@/components/ui/button'
import { useAuthStore } from '@/lib/stores/auth-store'
import { authApi } from '@/lib/api'

const NAV = [
  {
    label: 'PROPOSALS',
    items: [
      { href: '/dashboard',        label: 'Current',        icon: LayoutDashboard },
      { href: '/proposals',        label: 'Archive',        icon: Archive },
      { href: '/templates',        label: 'Templates',      icon: FileText },
      { href: '/calculators',      label: 'Calculators',    icon: Calculator },
    ],
  },
  {
    label: 'EVIDENCE',
    items: [
      { href: '/library', label: 'Past Performance', icon: History },
    ],
  },
  {
    label: 'ACCOUNT',
    items: [
      { href: '/profile',  label: 'Profile',  icon: Building2 },
      { href: '/security', label: 'Security', icon: Shield },
    ],
  },
]

/** "Ada Lovelace" → "AL". Falls back to the email's first letter. */
function initialsOf(name?: string, email?: string) {
  const parts = (name ?? '').trim().split(/\s+/).filter(Boolean)
  if (parts.length >= 2) return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase()
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase()
  return (email ?? '?').slice(0, 1).toUpperCase()
}

export default function AppLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname()
  const router = useRouter()
  const clearSession = useAuthStore((s) => s.clearSession)
  const user = useAuthStore((s) => s.user)

  // The proposal currently open, if any: /proposals/{id}/… where id is a real
  // id and not the "new" flow. Drives the contextual Workspace/Compliance links.
  const openProposalId = (() => {
    const m = pathname.match(/^\/proposals\/([^/]+)/)
    const id = m?.[1]
    return id && id !== 'new' ? id : null
  })()

  const topNav = [
    { href: '/dashboard', label: 'Dashboard' },
    { href: '/library', label: 'Past Performance' },
    ...(openProposalId
      ? [
          { href: `/proposals/${openProposalId}/workspace`, label: 'Workspace' },
          { href: `/proposals/${openProposalId}/compliance`, label: 'Compliance' },
        ]
      : []),
  ]

  // Exact match, or a real path segment beneath it — a plain startsWith lit
  // "/proposals" for "/proposals-archive" and lit every nested route at once.
  const isActive = (href: string) => pathname === href || pathname.startsWith(href + '/')

  async function handleLogout() {
    // Revoke server-side first so the refresh token can't be rotated again;
    // clearing local state alone would leave the session alive for 30 days.
    // No argument: the token travels as the HttpOnly cookie.
    try {
      await authApi.logout()
    } catch {
      // A failed revoke must not strand the user in a session they've left.
    }
    // Clears in-memory state and the route-guard marker; the server already
    // revoked the refresh token and expired its HttpOnly cookie.
    clearSession()
    router.push('/login')
  }

  return (
    <div className="min-h-screen bg-[var(--bg-secondary)]">
      {/* Top nav */}
      <header className="top-nav">
        <Link href="/dashboard" className="flex items-center gap-2 shrink-0">
          <div className="w-6 h-6 rounded bg-primary-600 flex items-center justify-center">
            <ShieldCheck className="w-3.5 h-3.5 text-white" />
          </div>
          <span className="text-sm font-medium">ProposalAI</span>
        </Link>

        {/* Center nav links.
            Workspace and Compliance are per-proposal routes — they only exist
            under /proposals/{id}. They used to sit here as fixed hrefs, so
            "Workspace" pointed at /proposals/workspace, which the router read
            as a proposal whose id is the literal string "workspace", and
            "Compliance" just went to the proposals list. Both are now built
            from the proposal currently open, and hidden when none is. */}
        <nav className="flex items-center gap-0.5 ml-4">
          {topNav.map((link) => (
            <Link
              key={link.href}
              href={link.href}
              className={cn(
                'px-3 py-1 rounded text-xs transition-colors',
                isActive(link.href)
                  ? 'text-[var(--text-primary)] font-medium bg-[var(--bg-secondary)]'
                  : 'text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-secondary)]'
              )}
            >
              {link.label}
            </Link>
          ))}
        </nav>

        <div className="ml-auto flex items-center gap-2">
          <button className="w-7 h-7 flex items-center justify-center rounded hover:bg-[var(--bg-secondary)] text-[var(--text-secondary)] transition-colors">
            <Bell className="w-4 h-4" />
          </button>
          {/* asChild, not a Link nested inside the button: a <a> inside a
              <button> is invalid HTML and browsers refuse to navigate it. */}
          <Button variant="primary" size="sm" icon={<Plus className="w-3.5 h-3.5" />} asChild>
            <Link href="/proposals/new">New proposal</Link>
          </Button>
          <div
            title={user?.email}
            className="w-7 h-7 rounded-full bg-primary-100 flex items-center justify-center text-[10px] font-medium text-primary-800 cursor-pointer"
          >
            {initialsOf(user?.name, user?.email)}
          </div>
        </div>
      </header>

      {/* Sidebar */}
      <aside className="sidebar scrollbar-thin">
        <div className="py-3">
          {NAV.map((group) => (
            <div key={group.label} className="mb-4">
              <p className="px-4 mb-1 text-[10px] font-medium text-[var(--text-tertiary)] tracking-wider uppercase">
                {group.label}
              </p>
              {group.items.map((item) => {
                const Icon = item.icon
                const active = pathname === item.href || pathname.startsWith(item.href + '/')
                return (
                  <Link
                    key={item.href}
                    href={item.href}
                    className={cn(
                      'flex items-center gap-2.5 mx-2 px-2 py-1.5 rounded text-xs transition-colors',
                      active
                        ? 'bg-primary-50 text-primary-600 font-medium'
                        : 'text-[var(--text-secondary)] hover:bg-[var(--bg-secondary)] hover:text-[var(--text-primary)]'
                    )}
                  >
                    <Icon className="w-3.5 h-3.5 shrink-0" />
                    {item.label}
                  </Link>
                )
              })}
            </div>
          ))}

          {/* Bottom items */}
          <div className="absolute bottom-0 left-0 right-0 border-t border-[var(--border-subtle)] py-2 bg-[var(--bg-primary)]">
            <Link href="#" className="flex items-center gap-2.5 mx-2 px-2 py-1.5 rounded text-xs text-[var(--text-secondary)] hover:bg-[var(--bg-secondary)] transition-colors">
              <HelpCircle className="w-3.5 h-3.5" /> Help
            </Link>
            <button onClick={handleLogout} className="w-full flex items-center gap-2.5 mx-2 px-2 py-1.5 rounded text-xs text-[var(--text-secondary)] hover:bg-[var(--bg-secondary)] transition-colors">
              <LogOut className="w-3.5 h-3.5" /> Logout
            </button>
          </div>
        </div>
      </aside>

      {/* Page content */}
      <main className="main-content">
        {children}
      </main>
    </div>
  )
}