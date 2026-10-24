import { useState } from 'react'
import { Check, RotateCcw, X } from 'lucide-react'
import clsx from 'clsx'
import type { Recommendation } from '../../types/contract'
import { useDecisions } from '../../store/decisions'
import { formatINR } from '../../lib/format'
import { optionLabel } from '../../lib/labels'

/** Accept (with a choice of option when a card has several) / reject / undo. */
export function DecideControl({ r, compact = false }: { r: Recommendation; compact?: boolean }) {
  const decision = useDecisions((s) => s.decisions[r.resource.resource_id])
  const accept = useDecisions((s) => s.accept)
  const reject = useDecisions((s) => s.reject)
  const clear = useDecisions((s) => s.clear)
  const choices = Object.keys(r.options).filter((k) => k !== 'none')
  const [choice, setChoice] = useState(decision?.status === 'accepted' ? decision.optionKey : r.default_option)
  const stop = (e: React.SyntheticEvent) => e.stopPropagation()

  if (decision) {
    const accepted = decision.status === 'accepted'
    return (
      <div className="flex items-center justify-end gap-2" onClick={stop}>
        <span
          className={clsx('truncate rounded-full px-2 py-0.5 text-2xs font-semibold', accepted ? 'bg-save-600 text-white' : 'bg-slate-200 text-slate-600')}
          data-testid="decision-status"
        >
          {accepted ? `Accepted${choices.length > 1 ? ` · ${optionLabel(decision.optionKey)}` : ''}` : 'Rejected'}
        </span>
        <button className="btn-ghost px-1.5 py-1" onClick={() => clear(r.resource.resource_id)} aria-label={`Undo decision for ${r.resource.name}`} title="Undo">
          <RotateCcw size={14} />
        </button>
      </div>
    )
  }

  return (
    <div className="flex items-center justify-end gap-1.5" onClick={stop}>
      {choices.length > 1 && (
        <select
          className={clsx('input w-0 min-w-0 flex-1 py-1 text-xs', 'max-w-[170px]')}
          value={choice}
          onChange={(e) => setChoice(e.target.value)}
          aria-label={`Option for ${r.resource.name}`}
          data-testid="option-select"
        >
          {choices.map((k) => (
            <option key={k} value={k}>
              {optionLabel(k)} · {formatINR(r.options[k].saving_inr)}
            </option>
          ))}
        </select>
      )}
      <button
        className="btn border border-save-600/40 bg-save-50 px-2 py-1 text-save-700 hover:bg-save-100"
        onClick={() => accept(r, choice)}
        aria-label={`Accept ${r.resource.name}`}
        title="Accept"
      >
        <Check size={14} /> {!compact && choices.length <= 1 && 'Accept'}
      </button>
      <button className="btn-outline px-2 py-1" onClick={() => reject(r)} aria-label={`Reject ${r.resource.name}`} title="Reject">
        <X size={14} />
      </button>
    </div>
  )
}
