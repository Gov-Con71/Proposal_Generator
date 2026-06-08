'use client'
import { useState } from 'react'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'

export default function CalculatorsPage() {
  const [direct, setDirect]   = useState(100000)
  const [fringe, setFringe]   = useState(32.5)
  const [overhead, setOverhead] = useState(14.2)
  const [ga, setGa]           = useState(8.9)
  const [profit, setProfit]   = useState(10)

  const fringeAmt   = direct * (fringe / 100)
  const totalDirect = direct + fringeAmt
  const overheadAmt = totalDirect * (overhead / 100)
  const subtotal    = totalDirect + overheadAmt
  const gaAmt       = subtotal * (ga / 100)
  const subtotal2   = subtotal + gaAmt
  const profitAmt   = subtotal2 * (profit / 100)
  const total       = subtotal2 + profitAmt

  function fmt(n: number) {
    return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 }).format(n)
  }

  return (
    <div className="page-padding">
      <h1 className="text-lg font-medium mb-1">Pricing Calculator</h1>
      <p className="text-xs text-[var(--text-secondary)] mb-5">Compute fully-burdened cost estimates for your proposal.</p>

      <div className="grid grid-cols-2 gap-4 max-w-2xl">
        <Card>
          <h3 className="text-xs font-medium mb-3">Inputs</h3>
          <div className="flex flex-col gap-3">
            <Input label="Direct Labor ($)"    type="number" value={direct}   onChange={(e) => setDirect(+e.target.value)} />
            <Input label="Fringe Rate (%)"     type="number" value={fringe}   onChange={(e) => setFringe(+e.target.value)} />
            <Input label="Overhead Rate (%)"   type="number" value={overhead} onChange={(e) => setOverhead(+e.target.value)} />
            <Input label="G&A Rate (%)"        type="number" value={ga}       onChange={(e) => setGa(+e.target.value)} />
            <Input label="Profit Margin (%)"   type="number" value={profit}   onChange={(e) => setProfit(+e.target.value)} />
          </div>
        </Card>

        <Card>
          <h3 className="text-xs font-medium mb-3">Breakdown</h3>
          <div className="flex flex-col gap-2 text-xs">
            {[
              { label: 'Direct Labor',   value: fmt(direct) },
              { label: `Fringe (${fringe}%)`, value: fmt(fringeAmt) },
              { label: 'Total Direct',   value: fmt(totalDirect), bold: true },
              { label: `Overhead (${overhead}%)`, value: fmt(overheadAmt) },
              { label: `G&A (${ga}%)`,   value: fmt(gaAmt) },
              { label: `Profit (${profit}%)`, value: fmt(profitAmt) },
            ].map((row) => (
              <div key={row.label} className={`flex justify-between py-1.5 border-b border-[var(--border-subtle)] last:border-0 ${row.bold ? 'font-medium' : ''}`}>
                <span className="text-[var(--text-secondary)]">{row.label}</span>
                <span>{row.value}</span>
              </div>
            ))}
            <div className="flex justify-between pt-2 text-sm font-medium text-primary-600">
              <span>Total Price</span>
              <span>{fmt(total)}</span>
            </div>
          </div>
        </Card>
      </div>
    </div>
  )
}