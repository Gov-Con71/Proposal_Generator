'use client'
import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { Download } from 'lucide-react'
import { use } from 'react'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils/cn'

export default function ProposalLayout({
  children,
  params,
}: {
  children: React.ReactNode
  params: Promise<{ id: string }>
}) {
  const { id } = use(params)
  const pathname = usePathname()

  // Handle the "new" route case
  if (id === 'new') {
    return <>{children}</>
  }

  const tabs = [
    { href: `/proposals/${id}/workspace`, label: 'Workspace' },
    { href: `/proposals/${id}/compliance`, label: 'Compliance' },
    { href: `/proposals/${id}/export`, label: 'Export' },
  ]

  return (
    <div>
      <div className="flex items-center gap-4 px-6 py-2 bg-white border-b border-neutral-100">
        <div className="flex items-center gap-1">
          {tabs.map((tab) => (
            <Link
              key={tab.href}
              href={tab.href}
              className={cn(
                'px-3 py-1.5 rounded text-xs transition-colors',
                pathname === tab.href
                  ? 'bg-neutral-100 text-neutral-800 font-medium'
                  : 'text-neutral-500 hover:text-neutral-800 hover:bg-neutral-100'
              )}
            >
              {tab.label}
            </Link>
          ))}
        </div>
        <div className="ml-auto">
          <Button variant="default" size="sm" asChild>
            <Link href={`/proposals/${id}/export`}>
              <Download className="w-3.5 h-3.5" />
              Export
            </Link>
          </Button>
        </div>
      </div>
      {children}
    </div>
  )
}