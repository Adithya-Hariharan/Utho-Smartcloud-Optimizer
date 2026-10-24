import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { ArrowRight, Bell } from 'lucide-react'
import clsx from 'clsx'
import { Page } from '../components/layout/AppShell'
import { ErrorNote, Loading, RiskChip, Stat } from '../components/common/ui'
import { BillTrendChart, GrowthWaterfall, type WaterfallBy } from '../components/charts/BillCharts'
import { DecideControl } from '../components/recs/DecideControl'
import { useAlerts, useAssumptions, useForecast, useSummary } from '../api/data'
import { useRecs } from '../api/recs'
import { formatCompactINR, formatDateIST, formatINR, formatNum, formatPct, formatWindow, titleCase } from '../lib/format'
import { optionLabel, titleEnv } from '../lib/labels'
import { useResourceDrawer } from '../lib/useDrawer'
import type { ReasonCode } from '../types/contract'

/** Resources that are pure waste: idle, orphaned, unused or stopped for weeks. */
const WASTE: ReasonCode[] = ['IDLE', 'ORPHAN_VOLUME', 'UNUSED_IP', 'STOPPED_VM']
const BY_LABEL: Record<WaterfallBy, string> = { env: 'by env', team: 'by team', age: 'new resources' }

export default function Overview() {
  const meta = useAssumptions()
  const summary = useSummary()
  const forecast = useForecast(90)
  const recs = useRecs()
  const alerts = useAlerts()
  const drawer = useResourceDrawer()
  const [by, setBy] = useState<WaterfallBy>('env')

  const story = useMemo(() => {
    const g = summary.data?.growth_waterfall
    if (!g) return null
    const env = (k: string) => g.by_env.find((x) => x.key === k)?.delta_inr ?? 0
    const growth = g.last30.total_inr - g.first30.total_inr
    const nonProd = env('staging') + env('dev')
    const fresh = g.by_age.find((x) => x.key === 'new resources')?.delta_inr ?? 0
    return { growth, nonProdShare: nonProd / growth, staging: env('staging'), dev: env('dev'), prod: env('prod'), topTeam: g.by_team[0], newCount: g.new_resources.length, fresh }
  }, [summary.data])

  const top = useMemo(() => {
    const items = (recs.data?.items ?? []).filter((r) => r.verdict === 'recommend' && r.risk?.level === 'Low')
    return items.sort((a, b) => b.options[b.default_option].saving_inr - a.options[a.default_option].saving_inr).slice(0, 5)
  }, [recs.data])

  if (summary.isLoading || recs.isLoading || meta.isLoading) return <Page title="Overview"><Loading /></Page>
  if (!summary.data || !recs.data || !meta.data) return <Page title="Overview"><ErrorNote error={summary.error ?? recs.error ?? meta.error} /></Page>

  const s = summary.data
  const g = s.growth_waterfall
  const waste = recs.data.items.filter((r) => r.verdict === 'recommend' && WASTE.includes(r.reason_code))
  const wasteInr = waste.reduce((t, r) => t + r.current.monthly_inr, 0)
  const critical = alerts.data?.items.filter((a) => a.severity === 'critical').length ?? 0
  const co2 = forecast.data?.carbon

  return (
    <Page
      title="Overview"
      subtitle={`Billing ${formatDateIST(g.first30.start + 'T00:00:00+05:30')} – ${formatDateIST(g.last30.end + 'T00:00:00+05:30')} · utilisation ${formatWindow(meta.data.data_window.start, meta.data.data_window.end)} (IST)`}
    >
      <div className="mb-4 grid grid-cols-5 gap-3">
        <Stat
          label="Monthly bill"
          value={formatINR(s.monthly_before_inr)}
          sub="current run-rate, ex-GST"
          how="Σ current monthly price of every resource (last billed day × 730/24). The same figure is 'Now' on the Recommendations page."
          testId="kpi-bill"
        />
        <Stat
          label="Bill trend"
          value={`+${formatPct((g.growth_ratio - 1) * 100)}`}
          sub={`${formatCompactINR(g.first30.total_inr)} → ${formatCompactINR(g.last30.total_inr)} per 30 days`}
          how="Last 30 billed days ÷ first 30 billed days of the 180-day history. Calendar months are not used: April and October are partial."
          tone="danger"
          testId="kpi-growth"
        />
        <Stat
          label="Waste"
          value={`${formatINR(wasteInr)}/mo`}
          sub={`${waste.length} idle, orphaned or stopped resources`}
          how="Σ current monthly cost of resources recommended for stop, delete or release because they do no work: idle VMs, orphan volumes, unused IPs, VMs stopped 30+ days."
          tone="danger"
          testId="kpi-waste"
        />
        <Stat
          label="Potential saving"
          value={`${formatINR(s.monthly_before_inr - s.potential_after_inr)}/mo`}
          sub={`${formatPct(s.potential_saving_pct)} of the bill (Default preset)`}
          how="From /api/summary: monthly bill − potential after, if every Default-preset recommendation were accepted."
          tone="save"
          testId="kpi-potential"
        />
        <Stat
          label="CO₂ avoidable"
          value={co2 ? `${formatNum(co2.potential_kg_co2_month)} kg/mo` : '…'}
          sub={co2 ? `${formatNum(co2.potential_kwh_month)} kWh of ${formatNum(co2.fleet_kwh_month)} kWh/month` : 'loading'}
          how={
            co2
              ? `Cloud Carbon Footprint: ${co2.coefficients.w_per_vcpu_min}–${co2.coefficients.w_per_vcpu_max} W per vCPU, ${co2.coefficients.w_per_gb_ram} W/GB, PUE ${co2.coefficients.pue}, India grid ${co2.coefficients.kg_co2_per_kwh} kg/kWh.`
              : 'Loading /api/forecast…'
          }
          tone="save"
          testId="kpi-co2"
        />
      </div>

      {story && (
        <div className="card card-pad mb-4 border-sky-100 bg-sky-50/60 text-sm leading-relaxed text-slate-700" data-testid="growth-story">
          The bill grew <b className="num">{formatINR(story.growth)}</b> per 30 days.{' '}
          <b>{formatPct(story.nonProdShare * 100, 0)} of that growth is non-prod</b>: staging <span className="num">+{formatINR(story.staging)}</span>, dev{' '}
          <span className="num">+{formatINR(story.dev)}</span>, against prod <span className="num">{story.prod >= 0 ? '+' : ''}{formatINR(story.prod)}</span>.{' '}
          {story.newCount} resources created after the first month add <span className="num">+{formatINR(story.fresh)}</span>; the {story.topTeam.key} team grew most (
          <span className="num">+{formatINR(story.topTeam.delta_inr)}</span>).
          {critical > 0 && (
            <Link to="/alerts" className="ml-2 inline-flex items-center gap-1 text-danger-700 hover:underline">
              <Bell size={13} /> {critical} critical alert{critical > 1 ? 's' : ''}
            </Link>
          )}
        </div>
      )}

      <div className="mb-4 grid grid-cols-5 gap-4">
        <section className="card card-pad col-span-3">
          <h2 className="mb-2 text-sm font-semibold text-slate-800">Daily cost by environment</h2>
          <BillTrendChart trend={s.bill_trend_6m} />
        </section>
        <section className="card card-pad col-span-2">
          <div className="mb-2 flex items-center justify-between">
            <h2 className="text-sm font-semibold text-slate-800">Bill Growth Explainer</h2>
            <div className="flex rounded-lg bg-slate-100 p-0.5 text-xs" role="group" aria-label="Break growth down by">
              {(['env', 'team', 'age'] as const).map((k) => (
                <button key={k} className={clsx('rounded-md px-2.5 py-1', by === k ? 'bg-white font-medium shadow-sm' : 'text-slate-500')} onClick={() => setBy(k)} aria-pressed={by === k}>
                  {BY_LABEL[k]}
                </button>
              ))}
            </div>
          </div>
          <GrowthWaterfall growth={g} by={by} />
        </section>
      </div>

      <section className="card">
        <div className="flex items-center justify-between border-b border-slate-100 px-4 py-3">
          <div>
            <h2 className="text-sm font-semibold text-slate-800">Monday morning list</h2>
            <p className="text-xs text-slate-500">Top 5 low-risk changes by saving. Act before lunch.</p>
          </div>
          <Link to="/recommendations" className="btn-ghost text-xs">
            All {recs.data.items.filter((r) => r.verdict === 'recommend').length} recommendations <ArrowRight size={13} />
          </Link>
        </div>
        <table className="w-full text-sm" data-testid="monday-list">
          <tbody className="divide-y divide-slate-100">
            {top.map((r) => (
              <tr key={r.rec_id} className="cursor-pointer hover:bg-slate-50" onClick={() => drawer.open(r.resource.resource_id)} data-testid={`monday-${r.resource.name}`}>
                <td className="td">
                  <div className="font-medium text-slate-900">{r.resource.name}</div>
                  <div className="text-2xs text-slate-500">{titleEnv(r.resource.env)} · {titleCase(r.resource.owner)}</div>
                </td>
                <td className="td text-slate-700">{optionLabel(r.default_option, r)}</td>
                <td className="td num text-right font-semibold text-save-700">{formatINR(r.options[r.default_option].saving_inr)}/mo</td>
                <td className="td"><RiskChip risk={r.risk} /></td>
                <td className="td"><DecideControl r={r} compact /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </Page>
  )
}
