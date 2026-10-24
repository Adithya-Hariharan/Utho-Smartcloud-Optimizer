import { useEffect, useRef, useState } from 'react'
import { Download, Loader2 } from 'lucide-react'
import type { RecEnvelope } from '../../types/contract'
import type { ExportFormat } from '../../types/api'
import { useDecisions } from '../../store/decisions'
import { useToasts } from '../../store/toasts'
import { postFile } from '../../api/client'
import { appliedKey } from '../../lib/cost'

const FORMATS: { format: ExportFormat; label: string }[] = [
  { format: 'csv', label: 'CSV (finance)' },
  { format: 'md', label: 'Markdown (ticket)' },
  { format: 'sh', label: 'apply.sh (dry run)' },
  { format: 'tf', label: 'Terraform snippet' },
]

/** Sends the accepted decisions to POST /api/export; the backend builds the file. */
export function ExportMenu({ env }: { env: RecEnvelope }) {
  const decisions = useDecisions((s) => s.decisions)
  const push = useToasts((s) => s.push)
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  const accepted = env.items
    .map((r) => ({ rec_id: r.rec_id, option_key: appliedKey(r, decisions[r.resource.resource_id]) }))
    .filter((a) => a.option_key !== 'none')

  useEffect(() => {
    if (!open) return
    const close = (e: MouseEvent) => !ref.current?.contains(e.target as Node) && setOpen(false)
    document.addEventListener('mousedown', close)
    return () => document.removeEventListener('mousedown', close)
  }, [open])

  const run = async (format: ExportFormat) => {
    setOpen(false)
    setBusy(true)
    try {
      const { blob, filename } = await postFile('/export', { accepted, format })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = filename
      document.body.appendChild(a)
      a.click()
      a.remove()
      setTimeout(() => URL.revokeObjectURL(url), 1000)
    } catch (e) {
      push({ tone: 'warn', title: 'Export failed', body: (e as Error).message })
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="relative" ref={ref}>
      <button className="btn-outline btn-sm" disabled={!accepted.length || busy} onClick={() => setOpen(!open)} aria-haspopup="menu" aria-expanded={open} data-testid="export-button">
        {busy ? <Loader2 size={13} className="animate-spin" aria-hidden /> : <Download size={13} />} Export {accepted.length ? `(${accepted.length})` : ''}
      </button>
      {open && (
        <div role="menu" className="absolute right-0 z-30 mt-1.5 w-52 animate-fade-in overflow-hidden rounded-lg border border-slate-200 bg-white py-1 shadow-pop">
          {FORMATS.map((f) => (
            <button key={f.format} role="menuitem" className="block w-full px-3 py-2 text-left text-sm text-slate-700 transition-colors hover:bg-sky-50 hover:text-slate-900" onClick={() => run(f.format)}>
              {f.label}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
