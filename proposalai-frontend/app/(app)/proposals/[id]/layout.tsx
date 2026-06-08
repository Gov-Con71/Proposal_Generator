'use client'
import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { Download } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils/cn'

export default function ProposalLayout({
  children,
  params,
}: {
  children: React.ReactNode
  params: { id: string }
}) {
  const pathname = usePathname()

  const tabs = [
    { href: `/proposals/${params.id}/workspace`,  label: 'Workspace' },
    { href: `/proposals/${params.id}/compliance`, label: 'Compliance' },
    { href: `/proposals/${params.id}/export`,     label: 'Export' },
  ]

  return (
    <div>
      {/* Per-proposal sub-nav */}
      <div className="flex items-center gap-4 px-6 py-2 bg-[var(--bg-primary)] border-b border-[var(--border-subtle)]">
        <div className="flex items-center gap-1">
          {tabs.map((tab) => (
            <Link
              key={tab.href}
              href={tab.href}
              className={cn(
                'px-3 py-1.5 rounded text-xs transition-colors',
                pathname === tab.href
                  ? 'bg-[var(--bg-secondary)] text-[var(--text-primary)] font-medium'
                  : 'text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-secondary)]'
              )}
            >
              {tab.label}
            </Link>
          ))}
        </div>
        <div className="ml-auto">
          <Button variant="default" size="sm" icon={<Download className="w-3.5 h-3.5" />} asChild>
            <Link href={`/proposals/${params.id}/export`}>Export</Link>
          </Button>
        </div>
      </div>
      {children}
    </div>
  )
}