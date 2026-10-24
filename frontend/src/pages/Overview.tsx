import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { ArrowRight, Bell } from 'lucide-react'
import { Page } from '../components/layout/AppShell'
import { ChartPanel, Empty, ErrorNote, Fact, HowTip, Loading, Panel, RiskChip, Segmented } from '../components/common/ui'
import { BillTrendChart, GrowthWaterfall, type WaterfallBy } from '../components/charts/BillCharts'
import { DecideControl } from '../components/recs/DecideControl'
import { useAlerts, useAssumptions, useForecast, useSummary } from '../api/data'
import { useRecs } from '../api/recs'
import { formatCompactINR, formatDateIST, formatINR, formatNum, formatPct, formatWindow, titleCase } from '../lib/format'
import { optionLabel, titleEnv } from '../lib/labels'
import { useResourceDrawer } from '../lib/useDrawer'
import { potential } from '../lib/cost'
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
  // follows the preset switch (/api/summary is Default-only); equals summary's figure under Default
  const pot = potential(recs.data.items)
  const presetLabel = meta.data.presets.find((x) => x.id === recs.data.preset)?.label ?? recs.data.preset

  return (
    <Page
      title="Overview"
      subtitle={`Billing ${formatDateIST(g.first30.start + 'T00:00:00+05:30')} – ${formatDateIST(g.last30.end + 'T00:00:00+05:30')} · utilisation ${formatWindow(meta.data.data_window.start, meta.data.data_window.end)} (IST)`}
    >
      <div className="mb-4 grid gap-4 lg:grid-cols-[minmax(0,1.45fr)_minmax(0,1fr)]">
        <section className="card flex flex-col p-5" aria-label="Monthly bill">
          <div className="label">
            <HowTip how="Σ current monthly price of every resource (last billed day × 730/24). The same figure is 'Now' on the Recommendations page.">Monthly bill</HowTip>
          </div>
          <div className="mt-2 flex flex-wrap items-end gap-x-4 gap-y-1.5">
            <div className="num text-[44px] font-semibold leading-none text-slate-900" style={{ letterSpacing: '-0.03em' }} data-testid="kpi-bill">
              {formatINR(s.monthly_before_inr)}
            </div>
            <div className="flex items-center gap-2 pb-1">
              <HowTip how="Last 30 billed days ÷ first 30 billed days of the 180-day history. Calendar months are not used: April and October are partial.">
                <span className="num text-lg font-semibold text-danger-700">
                  <span data-testid="kpi-growth">{`+${formatPct((g.growth_ratio - 1) * 100)}`}</span>
                </span>
                <span className="text-sm text-slate-700">growth in 6 months</span>
              </HowTip>
            </div>
          </div>
          <div className="num mt-2 text-[13px] text-slate-600">
            current run-rate, ex-GST · {formatCompactINR(g.first30.total_inr)} → {formatCompactINR(g.last30.total_inr)} per 30 days
          </div>
          {story && (
            <p className="mt-4 border-t border-slate-200 pt-4 text-sm leading-relaxed text-slate-700" data-testid="growth-story">
              The bill grew <b className="num font-semibold text-slate-900">{formatINR(story.growth)}</b> per 30 days.{' '}
              <b className="font-semibold text-slate-900">{formatPct(story.nonProdShare * 100, 0)} of that growth is non-prod</b>: staging <span className="num">+{formatINR(story.staging)}</span>, dev{' '}
              <span className="num">+{formatINR(story.dev)}</span>, against prod <span className="num">{story.prod >= 0 ? '+' : ''}{formatINR(story.prod)}</span>.{' '}
              {story.newCount} resources created after the first month add <span className="num">+{formatINR(story.fresh)}</span>; the {story.topTeam.key} team grew most (
              <span className="num">+{formatINR(story.topTeam.delta_inr)}</span>).
              {critical > 0 && (
                <Link to="/alerts" className="ml-2 inline-flex items-center gap-1 font-medium text-danger-700 hover:underline">
                  <Bell size={13} aria-hidden /> {critical} critical alert{critical > 1 ? 's' : ''}
                </Link>
              )}
            </p>
          )}
        </section>

        <section className="card divide-y divide-slate-200" aria-label="Savings and waste">
          <Fact
            label="Potential saving"
            tone="save"
            value={`${formatINR(pot.saving)}/mo`}
            sub={`${formatPct(pot.pct)} of the bill (${presetLabel} preset)`}
            how={`Σ default-option saving of the ${pot.count} ${presetLabel}-preset recommendations, if every one were accepted. Same figure as 'Potential' on the Recommendations page.`}
            testId="kpi-potential"
          />
          <Fact
            label="Waste"
            tone="danger"
            value={`${formatINR(wasteInr)}/mo`}
            sub={`${waste.length} idle, orphaned or stopped resources`}
            how="Σ current monthly cost of resources recommended for stop, delete or release because they do no work: idle VMs, orphan volumes, unused IPs, VMs stopped 30+ days."
            testId="kpi-waste"
          />
          <Fact
            label="CO₂ avoidable"
            tone="save"
            value={co2 ? `${formatNum(co2.potential_kg_co2_month)} kg/mo` : '…'}
            sub={co2 ? `${formatNum(co2.potential_kwh_month)} kWh of ${formatNum(co2.fleet_kwh_month)} kWh/month` : 'loading'}
            how={
              co2
                ? `Cloud Carbon Footprint: ${co2.coefficients.w_per_vcpu_min}–${co2.coefficients.w_per_vcpu_max} W per vCPU, ${co2.coefficients.w_per_gb_ram} W/GB, PUE ${co2.coefficients.pue}, India grid ${co2.coefficients.kg_co2_per_kwh} kg/kWh.`
                : 'Loading /api/forecast…'
            }
            testId="kpi-co2"
          />
        </section>
      </div>

      <div className="mb-4 grid gap-4 lg:grid-cols-5">
        <ChartPanel title="Daily cost by environment" sub="Billed per day, stacked by environment, last 180 days" className="lg:col-span-3">
          <BillTrendChart trend={s.bill_trend_6m} />
        </ChartPanel>
        <ChartPanel
          title="Bill Growth Explainer"
          sub="First 30 billed days to last 30, split by cause"
          className="lg:col-span-2"
          actions={<Segmented label="Break growth down by" value={by} onChange={setBy} options={(['env', 'team', 'age'] as const).map((k) => ({ value: k, label: BY_LABEL[k] }))} />}
        >
          <GrowthWaterfall growth={g} by={by} />
        </ChartPanel>
      </div>

      <Panel
        flush
        title="Monday morning list"
        sub="Top 5 low-risk changes by saving. Act before lunch."
        actions={
          <Link to="/recommendations" className="btn-ghost btn-sm">
            All {recs.data.items.filter((r) => r.verdict === 'recommend').length} recommendations <ArrowRight size={13} />
          </Link>
        }
      >
        {top.length ? (
          <table className="tbl tbl-stack" data-testid="monday-list">
            <tbody>
              {top.map((r) => (
                <tr key={r.rec_id} className="row-link" onClick={() => drawer.open(r.resource.resource_id)} data-testid={`monday-${r.resource.name}`}>
                  <td className="td" data-m="main">
                    <div className="font-medium text-slate-900">{r.resource.name}</div>
                    <div className="text-2xs text-slate-500">{titleEnv(r.resource.env)} · {titleCase(r.resource.owner)}</div>
                  </td>
                  <td className="td text-slate-700" data-m="full">{optionLabel(r.default_option, r)}</td>
                  <td className="td num text-right font-semibold text-save-700" data-m="aside">{formatINR(r.options[r.default_option].saving_inr)}/mo</td>
                  <td className="td"><RiskChip risk={r.risk} /></td>
                  <td className="td" data-m="end"><DecideControl r={r} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <Empty hint="Every low-risk change is already decided, or none passed the safety checks.">No low-risk changes to act on</Empty>
        )}
      </Panel>
    </Page>
  )
}
