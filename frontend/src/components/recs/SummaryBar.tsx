import { ArrowRight } from 'lucide-react'
import type { RecEnvelope } from '../../types/contract'
import { useDecisions } from '../../store/decisions'
import { potential, totals } from '../../lib/cost'
import { formatCompactINR, formatINR, formatPct } from '../../lib/format'
import { ENV_ORDER, titleEnv } from '../../lib/labels'
import { HowTip } from '../common/ui'

/** Sticky before → after bar. Recomputed in the browser on every accept/reject. */
export function SummaryBar({ env }: { env: RecEnvelope }) {
  const decisions = useDecisions((s) => s.decisions)
  const t = totals(env.items, decisions)
  const p = potential(env.items)
  const maxEnv = Math.max(...Object.values(t.byEnv).map((e) => e.before))

  return (
    <div className="sticky top-0 z-20 -mx-6 mb-4 border-b border-slate-200 bg-white/95 px-6 py-3 backdrop-blur" data-testid="summary-bar">
      <div className="flex flex-wrap items-center gap-x-5 gap-y-2">
        <div>
          <div className="label">
            <HowTip how="Run-rate: Σ current monthly cost of every resource (plan + disk, IPs, volumes). Same figure as the Overview bill.">Now</HowTip>
          </div>
          <div className="num text-lg font-semibold text-slate-900" data-testid="summary-before">
            {formatINR(t.before)}
            <span className="text-xs font-normal text-slate-500">/mo</span>
          </div>
        </div>
        <ArrowRight className="text-slate-300" size={18} />
        <div>
          <div className="label">
            <HowTip how="Σ over resources of options[accepted].monthly_inr_after. Each resource counts once; resize + schedule uses its combined price, never the sum of both savings.">
              After accepted
            </HowTip>
          </div>
          <div className="num text-lg font-semibold text-slate-900" data-testid="summary-after">
            {formatINR(t.after)}
            <span className="text-xs font-normal text-slate-500">/mo</span>
          </div>
        </div>
        <div>
          <div className="label">Saving accepted</div>
          <div className="num text-lg font-semibold text-save-700" data-testid="summary-saving">
            {formatINR(t.saving)} <span className="text-xs font-medium">({formatPct(t.savingPct)})</span>
          </div>
        </div>
        <div className="h-9 w-px bg-slate-200" />
        <div>
          <div className="label">
            <HowTip how={`Σ default-option saving of all ${p.count} recommendations if every one were accepted.`}>Potential</HowTip>
          </div>
          <div className="num text-sm font-semibold text-slate-700" data-testid="summary-potential">
            {formatINR(p.saving)}/mo · {formatPct(p.pct)}
          </div>
        </div>
        <div>
          <div className="label">
            <HowTip how="Accepted upsizes cost money. Shown on their own line, never hidden inside the saving.">Risk fixes</HowTip>
          </div>
          <div className="num text-sm font-semibold text-upsize-700" data-testid="summary-riskfixes">
            +{formatINR(t.riskFixes)}
          </div>
        </div>
        <div>
          <div className="label">
            <HowTip how="Changes saving under ₹500/month are dropped from the list and only counted here.">Below floor</HowTip>
          </div>
          <div className="num text-sm text-slate-600" data-testid="summary-belowfloor">
            {env.below_floor.count} item{env.below_floor.count === 1 ? '' : 's'} · {formatINR(env.below_floor.monthly_inr)}
          </div>
        </div>
        <div className="ml-auto grid w-[230px] grid-cols-[52px_1fr_auto] items-center gap-x-2 gap-y-0.5" aria-label="Before and after by environment">
          {ENV_ORDER.filter((e) => t.byEnv[e]).map((e) => {
            const b = t.byEnv[e]
            return (
              <div key={e} className="contents text-2xs">
                <span className="text-slate-500">{titleEnv(e === 'untagged' ? null : e)}</span>
                <span className="relative h-2.5 rounded bg-slate-100">
                  <span className="absolute inset-y-0 left-0 rounded bg-slate-300" style={{ width: `${(b.before / maxEnv) * 100}%` }} />
                  <span className="absolute inset-y-0 left-0 rounded bg-save-600" style={{ width: `${(b.after / maxEnv) * 100}%` }} />
                </span>
                <span className="num text-slate-600">
                  {formatCompactINR(b.before)}
                  {b.after !== b.before && <span className="text-save-700"> → {formatCompactINR(b.after)}</span>}
                </span>
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}
