import { useState } from 'react'
import { Check, RotateCcw, X } from 'lucide-react'
import clsx from 'clsx'
import type { Recommendation } from '../../types/contract'
import { useDecisions } from '../../store/decisions'
import { formatINR } from '../../lib/format'
import { optionLabel } from '../../lib/labels'

/**
 * Accept / Reject with words, never bare icons, so the two choices are obvious at a glance.
 * A card with several options adds a selector and the buttons shrink to icons to fit the row.
 */
export function DecideControl({ r, compact = false }: { r: Recommendation; compact?: boolean }) {
  const decision = useDecisions((s) => s.decisions[r.resource.resource_id])
  const accept = useDecisions((s) => s.accept)
  const reject = useDecisions((s) => s.reject)
  const clear = useDecisions((s) => s.clear)
  const choices = Object.keys(r.options).filter((k) => k !== 'none')
  const [choice, setChoice] = useState(decision?.status === 'accepted' ? decision.optionKey : r.default_option)
  const stop = (e: React.SyntheticEvent) => e.stopPropagation()
  const multi = choices.length > 1

  if (decision) {
    const accepted = decision.status === 'accepted'
    return (
      <div className="flex items-center justify-end gap-1.5" onClick={stop}>
        <span
          className={clsx('inline-flex h-7 min-w-0 animate-fade-in items-center gap-1 rounded-md px-2.5 text-xs font-medium', accepted ? 'bg-save-600 text-white' : 'bg-slate-100 text-slate-700 ring-1 ring-inset ring-slate-300')}
          data-testid="decision-status"
        >
          {accepted ? <Check size={13} aria-hidden className="shrink-0" /> : <X size={13} aria-hidden className="shrink-0" />}
          <span className="truncate">{accepted ? `Accepted${multi ? ` · ${optionLabel(decision.optionKey)}` : ''}` : 'Rejected'}</span>
        </span>
        <button className="btn-ghost btn-sm px-2" onClick={() => clear(r.resource.resource_id)} aria-label={`Undo decision for ${r.resource.name}`} title="Undo">
          <RotateCcw size={13} aria-hidden /> <span className="max-sm:hidden">Undo</span>
        </button>
      </div>
    )
  }

  const words = !multi && !compact
  return (
    <div className="flex items-center justify-end gap-1.5" onClick={stop}>
      {multi && (
        <select className="input input-sm w-0 min-w-[8rem] max-w-[170px] flex-1" value={choice} onChange={(e) => setChoice(e.target.value)} aria-label={`Option for ${r.resource.name}`} data-testid="option-select">
          {choices.map((k) => (
            <option key={k} value={k}>
              {optionLabel(k)} · {formatINR(r.options[k].saving_inr)}
            </option>
          ))}
        </select>
      )}
      <button className={clsx('btn-accept btn-sm', !words && 'w-8 px-0')} onClick={() => accept(r, choice)} aria-label={`Accept ${r.resource.name}`} title="Accept">
        <Check size={14} aria-hidden /> {words && 'Accept'}
      </button>
      <button className={clsx('btn-outline btn-sm', !words && 'w-8 px-0')} onClick={() => reject(r)} aria-label={`Reject ${r.resource.name}`} title="Reject">
        <X size={14} aria-hidden /> {words && 'Reject'}
      </button>
    </div>
  )
}
