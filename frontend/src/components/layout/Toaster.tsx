import { useEffect, useRef } from 'react'
import { X } from 'lucide-react'
import clsx from 'clsx'
import { useToasts } from '../../store/toasts'
import { useRecs } from '../../api/recs'
import { useUi } from '../../store/ui'
import { useDecisions } from '../../store/decisions'
import { reconcile } from '../../lib/cost'

export function Toaster() {
  const toasts = useToasts((s) => s.toasts)
  const dismiss = useToasts((s) => s.dismiss)
  return (
    <div className="pointer-events-none fixed bottom-4 right-4 z-[90] flex w-96 flex-col gap-2" aria-live="polite">
      {toasts.map((t) => (
        <div key={t.id} role="status" className={clsx('pointer-events-auto rounded-xl border bg-white px-4 py-3 shadow-lg', t.tone === 'warn' ? 'border-review-600/40' : 'border-slate-200')} data-testid="toast">
          <div className="flex items-start gap-2">
            <div className="flex-1">
              <div className="text-sm font-semibold text-slate-900">{t.title}</div>
              {t.body && <div className="mt-0.5 text-xs leading-relaxed text-slate-600">{t.body}</div>}
            </div>
            <button className="text-slate-400 hover:text-slate-700" onClick={() => dismiss(t.id)} aria-label="Dismiss">
              <X size={14} />
            </button>
          </div>
        </div>
      ))}
    </div>
  )
}

/**
 * F8: when the preset changes, decisions whose option or target no longer exists are dropped,
 * and the user is told which and why. Runs once per preset switch, after the new recs load.
 */
export function PresetReconciler() {
  const preset = useUi((s) => s.preset)
  const recs = useRecs()
  const push = useToasts((s) => s.push)
  const lastPreset = useRef(preset)

  useEffect(() => {
    if (!recs.data || recs.data.preset !== preset) return
    if (lastPreset.current === preset) return
    lastPreset.current = preset
    const { decisions, replaceAll } = useDecisions.getState()
    const { decisions: kept, reset } = reconcile(decisions, recs.data.items)
    if (!reset.length) return
    replaceAll(kept)
    push({
      tone: 'warn',
      title: `${reset.length} decision${reset.length > 1 ? 's' : ''} reset by the preset change`,
      body: reset.map((r) => `${r.name}: ${r.why}`).join(' · '),
    })
  }, [preset, recs.data, push])

  return null
}
