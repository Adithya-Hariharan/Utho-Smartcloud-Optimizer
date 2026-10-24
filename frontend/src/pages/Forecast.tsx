import { useMemo } from 'react'
import { Leaf } from 'lucide-react'
import { Page } from '../components/layout/AppShell'
import { ErrorNote, Loading, Stat } from '../components/common/ui'
import { ForecastChart } from '../components/charts/ForecastChart'
import { useForecast } from '../api/data'
import { useRecs } from '../api/recs'
import { useDecisions } from '../store/decisions'
import { appliedKey, totals } from '../lib/cost'
import { formatCompactINR, formatINR, formatNum } from '../lib/format'

/** Forecast & Green (PLAN §11.7): 90-day bill with and without accepted actions, plus energy and CO₂ saved. */
export default function Forecast() {
  const forecast = useForecast(90)
  const recs = useRecs()
  const decisions = useDecisions((s) => s.decisions)

  const accepted = useMemo(() => {
    if (!recs.data || !forecast.data) return null
    const t = totals(recs.data.items, decisions)
    let kwh = 0, kg = 0, n = 0
    for (const r of recs.data.items) {
      const key = appliedKey(r, decisions[r.resource.resource_id])
      if (key === 'none') continue
      const c = forecast.data.carbon.by_option[r.rec_id]?.[key]
      if (c) {
        kwh += c.kwh_month
        kg += c.kg_co2_month
        n++
      }
    }
    return { monthlySaving: t.before - t.after, kwh, kg, n }
  }, [recs.data, forecast.data, decisions])

  if (forecast.isLoading || recs.isLoading) return <Page title="Forecast & Green"><Loading /></Page>
  if (!forecast.data || !recs.data || !accepted) return <Page title="Forecast & Green"><ErrorNote error={forecast.error ?? recs.error} /></Page>
  const f = forecast.data
  const c = f.carbon
  const next90 = f.forecast.baseline.reduce((s, v) => s + v, 0)
  const next90With = next90 - (accepted.monthlySaving * 24 * 90) / 730

  return (
    <Page title="Forecast & Green" subtitle={`Next 90 days of billed cost (${f.method}), with and without the actions you accepted.`}>
      <div className="mb-4 grid grid-cols-4 gap-3">
        <Stat
          label="Next 90 days, as is"
          value={formatCompactINR(next90)}
          sub={`${formatINR(f.forecast.baseline[0])}/day → ${formatINR(f.forecast.baseline.at(-1)!)}/day`}
          how="Σ of the engine's daily forecast for the next 90 days (Holt-Winters, weekly season)."
          testId="fc-asis"
        />
        <Stat
          label="With accepted actions"
          value={formatCompactINR(next90With)}
          sub={accepted.monthlySaving ? `saves ${formatINR(accepted.monthlySaving)}/month` : 'accept recommendations to see this move'}
          how="Forecast − accepted monthly saving × 24/730 per day. The saving is the same 'after accepted' total as the Recommendations page."
          tone="save"
          testId="fc-with"
        />
        <Stat
          label="Energy saved"
          value={`${formatNum(accepted.kwh)} kWh/mo`}
          sub={`${accepted.n} accepted changes · fleet uses ${formatNum(c.fleet_kwh_month)} kWh/mo`}
          how={`Per accepted option, from /api/forecast: vCPU × (${c.coefficients.w_per_vcpu_min}–${c.coefficients.w_per_vcpu_max} W by utilisation) + RAM × ${c.coefficients.w_per_gb_ram} W/GB, × PUE ${c.coefficients.pue} × 730 h.`}
          testId="fc-kwh"
        />
        <Stat
          label="CO₂ avoided"
          value={`${formatNum(accepted.kg)} kg/mo`}
          sub={`of ${formatNum(c.potential_kg_co2_month)} kg/mo possible`}
          how={`kWh × ${c.coefficients.kg_co2_per_kwh} kg CO₂/kWh (India grid). ${c.coefficients.source}.`}
          tone="save"
          testId="fc-co2"
        />
      </div>

      <section className="card card-pad mb-4">
        <h2 className="mb-2 text-sm font-semibold text-slate-800">Daily billed cost: last 60 days and next 90</h2>
        <ForecastChart forecast={f} acceptedMonthlySaving={accepted.monthlySaving} />
      </section>

      <section className="card card-pad text-sm text-slate-700">
        <h2 className="mb-2 flex items-center gap-2 text-sm font-semibold text-slate-800">
          <Leaf size={15} className="text-save-600" /> How the carbon figures are computed
        </h2>
        <ul className="list-inside list-disc space-y-1 text-slate-600">
          <li>Power per VM: {c.coefficients.w_per_vcpu_min}–{c.coefficients.w_per_vcpu_max} W per vCPU scaled by CPU utilisation, plus {c.coefficients.w_per_gb_ram} W per GB of RAM.</li>
          <li>Data-centre overhead: PUE {c.coefficients.pue}. Grid intensity: {c.coefficients.kg_co2_per_kwh} kg CO₂ per kWh (India, CEA).</li>
          <li>Resizing keeps the work and removes idle capacity; scheduling scales by on-hours; stop and delete remove the VM's power entirely. Storage and network energy are not modelled.</li>
          <li>Source: {c.coefficients.source}. Today the fleet draws about {formatNum(c.fleet_kwh_month)} kWh ({formatNum(c.fleet_kg_co2_month)} kg CO₂) a month.</li>
        </ul>
      </section>
    </Page>
  )
}
