import type { QueryClient } from '@tanstack/react-query'
import { useProposalStore } from '@/lib/stores/Proposal-store'

const clients = new Set<QueryClient>()

export function registerPrivateCache(client: QueryClient) {
  clients.add(client)
  return () => { clients.delete(client) }
}

export function clearPrivateState() {
  for (const client of clients) {
    // Cancellation prevents late requests from repopulating a cleared cache.
    void client.cancelQueries()
    client.clear()
  }
  useProposalStore.getState().reset()
}
