import { redirect } from 'next/navigation'

export default function ProposalPage({ params }: { params: { id: string } }) {
  redirect(`/proposals/${params.id}/workspace`)
}