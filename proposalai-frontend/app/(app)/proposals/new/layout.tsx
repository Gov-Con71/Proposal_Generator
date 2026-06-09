export default function NewProposalLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-[calc(100vh-44px)] bg-[var(--bg-secondary)]">
      {children}
    </div>
  )
}