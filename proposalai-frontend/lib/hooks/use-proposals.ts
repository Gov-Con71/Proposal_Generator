import { useEffect, useState } from 'react'
import { fetchProposals } from '../api/proposals'

export default function useProposals(){
  const [data, setData] = useState<any[]>([])
  useEffect(()=>{ fetchProposals().then((d:any)=>setData(d)).catch(()=>{}) },[])
  return { data }
}
