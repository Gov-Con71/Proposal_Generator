import { apiFetch } from './client'

export async function fetchProposals(){
  return apiFetch('/proposals')
}
