import { useEffect, useRef, useState } from 'react'
import { ArrowRight, ChevronDown } from 'lucide-react'
import clsx from 'clsx'
import type { RecEnvelope } from '../../types/contract'
import { useDecisions } from '../../store/decisions'
import { potential, totals } from '../../lib/cost'
import { formatCompactINR, formatINR, formatPct } from '../../lib/format'
import { ENV_ORDER, titleEnv } from '../../lib/labels'
import { HowTip } from '../common/ui'

const BIG = { letterSpacing: '-0.025em' } as const

/** Sticky before → after strip. Recomputed in the browser on every accept/reject. */
export function SummaryBar({ env }: { env: RecEnvelope }) {
  const decisions = useDecisions((s) => s.decisions)
  const [more, setMore] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  const t = totals(env.items, decisions)
  const p = potential(env.items)
  const maxEnv = Math.max(...Object.values(t.byEnv).map((e) => e.before))
  const accepted = Object.values(decisions).filter((d) => d.status === 'accepted').length
  const progress = p.saving > 0 ? Math.min(100, Math.max(0, (t.saving / p.saving) * 100)) : 0
  const delta = t.before - t.after

  // the table header sticks just below this bar, whatever height it wraps to
  useEffect(() => {
    const el = ref.current
    if (!el) return
    const set = () => document.documentElement.style.setProperty('--summary-h', `${el.offsetHeight}px`)
    set()
    const ro = new ResizeObserver(set)
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  const secondary = clsx('lg:block', more ? 'block' : 'hidden')

  return (
    <div ref={ref} className="sticky top-0 z-20 -mx-1 bg-canvas px-1 pb-4 pt-1" data-testid="summary-bar">
      <div className="card grid overflow-clip lg:grid-cols-2 min-[1400px]:grid-cols-[auto_minmax(220px,1fr)_minmax(250px,auto)_minmax(290px,auto)]">
        {/* Now → After */}
        <div className="px-4 py-3.5 sm:px-5 lg:border-r lg:border-slate-200">
          <div className="flex items-start gap-4">
            <div>
              <div className="label">
                <HowTip how="Run-rate: Σ current monthly cost of every resource (plan + disk, IPs, volumes). Same figure as the Overview bill.">Now</HowTip>
              </div>
              <div className="num mt-1 text-[22px] font-semibold leading-none text-slate-900" style={BIG} data-testid="summary-before">
                {formatINR(t.before)}
                <span className="ml-0.5 text-xs font-normal text-slate-600">/mo</span>
              </div>
            </div>
            <ArrowRight className="mt-6 shrink-0 text-slate-400" size={16} aria-hidden />
            <div>
              <div className="label">
                <HowTip how="Σ over resources of options[accepted].monthly_inr_after. Each resource counts once; resize + schedule uses its combined price, never the sum of both savings.">
                  After accepted
                </HowTip>
              </div>
              <div className="num mt-1 text-[22px] font-semibold leading-none text-slate-900" style={BIG} data-testid="summary-after">
                {formatINR(t.after)}
                <span className="ml-0.5 text-xs font-normal text-slate-600">/mo</span>
              </div>
            </div>
          </div>
          <div className="num mt-2 text-xs text-slate-600">
            {delta > 0 ? `−${formatINR(delta)}/mo from today's run-rate` : delta < 0 ? `+${formatINR(-delta)}/mo from today's run-rate` : 'Accept changes to see the new run-rate'}
          </div>
        </div>

        {/* Saving accepted, with progress toward the potential */}
        <div className="border-t border-slate-200 px-4 py-3.5 sm:px-5 lg:border-t-0 min-[1400px]:border-r">
          <div className="flex items-baseline justify-between gap-3">
            <div className="label">Saving accepted</div>
            <div className="num text-xs text-slate-600">{accepted} accepted</div>
          </div>
          <div className={clsx('num mt-1 text-[22px] font-semibold leading-none transition-colors duration-200', t.saving > 0 ? 'text-save-700' : 'text-slate-500')} style={BIG} data-testid="summary-saving">
            {formatINR(t.saving)} <span className="text-xs font-medium">({formatPct(t.savingPct)})</span>
          </div>
          <div
            className="mt-3 h-2 overflow-hidden rounded-full bg-slate-100"
            role="progressbar"
            aria-label="Accepted saving as a share of the potential"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={Math.round(progress)}
          >
            <div className="h-full rounded-full bg-save-600 transition-[width] duration-300 ease-out" style={{ width: `${progress}%` }} />
          </div>
          <div className="num mt-2 whitespace-nowrap text-xs text-slate-600">
            {formatPct(progress, 0)} of the {formatINR(p.saving)}/mo possible
          </div>
        </div>

        <button className="btn-ghost btn-sm mx-4 my-1 justify-between border-t border-slate-200 lg:hidden" onClick={() => setMore(!more)} aria-expanded={more}>
          {more ? 'Hide details' : 'Show details'} <ChevronDown size={13} className={clsx('transition-transform duration-200', more && 'rotate-180')} aria-hidden />
        </button>

        {/* Potential, risk fixes, below floor */}
        <dl className={clsx('flex flex-col justify-center divide-y divide-slate-200/70 border-t border-slate-200 px-4 py-2 text-[13px] sm:px-5 lg:border-r min-[1400px]:border-t-0', secondary)}>
          <div className="flex items-baseline justify-between gap-4 py-1.5">
            <dt className="text-slate-600">
              <HowTip how={`Σ default-option saving of all ${p.count} recommendations if every one were accepted.`}>Potential</HowTip>
            </dt>
            <dd className="num whitespace-nowrap font-semibold text-slate-900" data-testid="summary-potential">
              {formatINR(p.saving)}/mo · {formatPct(p.pct)}
            </dd>
          </div>
          <div className="flex items-baseline justify-between gap-4 py-1.5">
            <dt className="text-slate-600">
              <HowTip how="Accepted upsizes cost money. Shown on their own line, never hidden inside the saving.">Risk fixes</HowTip>
            </dt>
            <dd className="num font-semibold text-upsize-700" data-testid="summary-riskfixes">
              +{formatINR(t.riskFixes)}
            </dd>
          </div>
          <div className="flex items-baseline justify-between gap-4 py-1.5">
            <dt className="text-slate-600">
              <HowTip how="Changes saving under ₹500/month are dropped from the list and only counted here.">Below floor</HowTip>
            </dt>
            <dd className="num font-medium text-slate-800" data-testid="summary-belowfloor">
              {env.below_floor.count} item{env.below_floor.count === 1 ? '' : 's'} · {formatINR(env.below_floor.monthly_inr)}
            </dd>
          </div>
        </dl>

        {/* By environment: grey = today, green = after accepted */}
        <div className={clsx('border-t border-slate-200 px-4 py-3.5 sm:px-5 min-[1400px]:border-t-0', secondary)} role="group" aria-label="Before and after by environment">
          <div className="mb-2.5 flex items-center justify-between gap-4">
            <div className="label whitespace-nowrap">By environment</div>
            <div className="flex items-center gap-3 whitespace-nowrap text-xs text-slate-600">
              <span className="inline-flex items-center gap-1">
                <span className="h-2 w-2 rounded-full bg-slate-300" aria-hidden /> today
              </span>
              <span className="inline-flex items-center gap-1">
                <span className="h-2 w-2 rounded-full bg-save-600" aria-hidden /> after
              </span>
            </div>
          </div>
          <div className="grid grid-cols-[58px_minmax(90px,1fr)_auto] items-center gap-x-3 gap-y-1.5">
            {ENV_ORDER.filter((e) => t.byEnv[e]).map((e) => {
              const b = t.byEnv[e]
              return (
                <div key={e} className="contents text-xs">
                  <span className="text-slate-700">{titleEnv(e === 'untagged' ? null : e)}</span>
                  <span className="relative h-2 overflow-hidden rounded-full bg-slate-100">
                    <span className="absolute inset-y-0 left-0 rounded-full bg-slate-300" style={{ width: `${(b.before / maxEnv) * 100}%` }} />
                    <span className="absolute inset-y-0 left-0 rounded-full bg-save-600 transition-[width] duration-300 ease-out" style={{ width: `${(b.after / maxEnv) * 100}%` }} />
                  </span>
                  <span className="num whitespace-nowrap text-right text-slate-700">
                    {formatCompactINR(b.before)}
                    {b.after !== b.before && <span className="font-medium text-save-700"> → {formatCompactINR(b.after)}</span>}
                  </span>
                </div>
              )
            })}
          </div>
        </div>
      </div>
    </div>
  )
}
