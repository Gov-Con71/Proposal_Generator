import apiClient from './client'

export async function fetchProposals(){
  return apiClient.get('/proposals').then((r) => r.data)
}
