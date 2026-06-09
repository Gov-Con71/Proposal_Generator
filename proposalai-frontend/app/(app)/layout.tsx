'use client'
import Link from 'next/link'
import { usePathname } from 'next/navigation'
import {
  ShieldCheck, LayoutDashboard, PenLine, Table2,
  History, Building2, Users, LogOut, HelpCircle,
  Shield, Bell, Plus, FileText, Calculator, Archive
} from 'lucide-react'
import { cn } from '@/lib/utils/cn'
import { Button } from '@/components/ui/button'

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
    label: 'ACCOUNT',
    items: [
      { href: '/profile',  label: 'Profile',  icon: Building2 },
      { href: '/security', label: 'Security', icon: Shield },
    ],
  },
]

export default function AppLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname()

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

        {/* Center nav links */}
        <nav className="flex items-center gap-0.5 ml-4">
          {[
            { href: '/dashboard',   label: 'Dashboard' },
            { href: '/proposals/workspace', label: 'Workspace' },
            { href: '/proposals',   label: 'Compliance' },
          ].map((link) => (
            <Link
              key={link.href}
              href={link.href}
              className={cn(
                'px-3 py-1 rounded text-xs transition-colors',
                pathname.startsWith(link.href)
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
          <Button variant="primary" size="sm" icon={<Plus className="w-3.5 h-3.5" />}>
            <Link href="/proposals/new" className="no-underline">New proposal</Link>
          </Button>
          <div className="w-7 h-7 rounded-full bg-primary-100 flex items-center justify-center text-[10px] font-medium text-primary-800 cursor-pointer">
            JS
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
            <Link href="/login" className="flex items-center gap-2.5 mx-2 px-2 py-1.5 rounded text-xs text-[var(--text-secondary)] hover:bg-[var(--bg-secondary)] transition-colors">
              <LogOut className="w-3.5 h-3.5" /> Logout
            </Link>
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