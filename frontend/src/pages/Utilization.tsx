import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import clsx from 'clsx'
import { Page } from '../components/layout/AppShell'
import { FilterBar, distinct, useUrlFilters } from '../components/common/FilterBar'
import { Empty, ErrorNote, Loading, Panel, Segmented, VerdictBadge } from '../components/common/ui'
import { Sparkline } from '../components/charts/Sparkline'
import { SERIES } from '../components/charts/theme'
import { FleetHeatmap } from '../components/charts/FleetHeatmap'
import { useAssumptions, useResources } from '../api/data'
import { useRecs } from '../api/recs'
import { formatINR, formatPct, titleCase } from '../lib/format'
import { REASON_LABEL, VERDICT_META, titleEnv } from '../lib/labels'
import type { ResourceRow, Verdict } from '../types/contract'

const KEYS = ['env', 'team', 'region', 'type', 'verdict', 'q']

/** URL filter values → GET /api/resources params (untagged env / unowned team are named values server-side). */
const apiValue = (key: string, v: string) => (v === '__none' ? (key === 'team' ? 'unowned' : 'untagged') : v || undefined)

export default function Utilization() {
  const filters = useUrlFilters(KEYS)
  const f = filters.values
  const fleet = useResources() // unfiltered, for the filter options
  const resources = useResources({ env: apiValue('env', f.env), team: apiValue('team', f.team), region: apiValue('region', f.region), type: apiValue('type', f.type) })
  const recs = useRecs()
  const meta = useAssumptions()
  const navigate = useNavigate()
  const [view, setView] = useState<'table' | 'heatmap'>('table')
  const [sort, setSort] = useState<{ key: 'name' | 'cpu' | 'mem' | 'cost'; dir: 1 | -1 }>({ key: 'cpu', dir: -1 })

  const verdictOf = useMemo(() => Object.fromEntries((recs.data?.items ?? []).map((r) => [r.resource.resource_id, r])), [recs.data])
  const all = fleet.data ?? []
  const rows = useMemo(() => {
    // region / env / team / type are already applied by the server
    const list = (resources.data ?? []).filter(
      (r) =>
        (!f.verdict || verdictOf[r.resource_id]?.verdict === f.verdict) &&
        (!f.q || r.name.toLowerCase().includes(f.q.toLowerCase())),
    )
    const val = (r: ResourceRow) =>
      sort.key === 'name' ? r.name : sort.key === 'cpu' ? r.stats?.cpu_p95 ?? -1 : sort.key === 'mem' ? r.stats?.mem_p95 ?? -1 : r.monthly_inr
    return list.sort((a, b) => {
      const x = val(a), y = val(b)
      return (typeof x === 'string' ? x.localeCompare(y as string) : (x as number) - (y as number)) * sort.dir
    })
  }, [resources.data, f.verdict, f.q, verdictOf, sort])

  if (resources.isLoading || recs.isLoading) return <Page title="Utilization"><Loading /></Page>
  if (!resources.data || !recs.data) return <Page title="Utilization"><ErrorNote error={resources.error ?? recs.error} /></Page>

  const heatRows = rows.filter((r) => r.type === 'vm' && r.daily_p95)
  const head = (key: typeof sort.key, label: string, right = false) => (
    <th className={clsx('th cursor-pointer select-none transition-colors hover:text-slate-800', right && 'text-right')} onClick={() => setSort((s) => ({ key, dir: s.key === key ? ((-s.dir) as 1 | -1) : -1 }))} aria-sort={sort.key === key ? (sort.dir === 1 ? 'ascending' : 'descending') : 'none'}>
      {label} {sort.key === key ? (sort.dir === 1 ? '↑' : '↓') : ''}
    </th>
  )

  return (
    <Page
      title="Utilization"
      subtitle={`${all.length} resources · 30 days at 5-minute resolution · ${meta.data?.counts.metric_rows.toLocaleString('en-IN') ?? ''} metric rows`}
      actions={
        <Segmented label="View" value={view} onChange={setView} options={[{ value: 'table', label: 'table' }, { value: 'heatmap', label: 'heatmap' }]} />
      }
    >
      <div className="mb-3">
        <FilterBar
          filters={filters}
          defs={[
            { key: 'env', label: 'Env', options: distinct(all, (r) => r.env, titleCase) },
            { key: 'team', label: 'Team', options: distinct(all, (r) => r.owner_team, titleCase) },
            { key: 'region', label: 'Region', options: distinct(all, (r) => r.region, titleCase) },
            { key: 'type', label: 'Type', options: distinct(all, (r) => r.type, (v) => v.toUpperCase()) },
            { key: 'verdict', label: 'Verdict', options: (Object.keys(VERDICT_META) as Verdict[]).map((v) => ({ value: v, label: VERDICT_META[v].label })) },
          ]}
          right={<span className="num text-xs text-slate-500" data-testid="util-count">{rows.length} shown</span>}
        />
      </div>

      {view === 'table' ? (
        <div className="card overflow-clip">
          <table className="tbl tbl-stack-lg tbl-compact" data-testid="fleet-table">
            <thead className="sticky top-0 z-10">
              <tr>
                {head('name', 'Resource')}
                <th className="th" data-m="hide">Plan</th>
                {head('cpu', 'CPU p95', true)}
                <th className="th text-right" data-m="hide">CPU p99</th>
                {head('mem', 'Mem p95', true)}
                <th className="th text-right" data-m="hide">Mem p99</th>
                <th className="th text-right" data-m="hide">Coverage</th>
                <th className="th">Daily p95 · 30 d</th>
                <th className="th">Verdict</th>
                {head('cost', '₹ / mo', true)}
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => {
                const rec = verdictOf[r.resource_id]
                return (
                  <tr key={r.resource_id} className="row-link" onClick={() => navigate(`/utilization/${r.resource_id}`)} data-testid={`util-row-${r.name}`}>
                    <td className="td" data-m="main">
                      <div className="font-medium text-slate-900">{r.name}</div>
                      <div className="text-2xs text-slate-500">
                        {r.type.toUpperCase()} · {titleEnv(r.env)} · {titleCase(r.owner_team ?? 'unowned')} · {titleCase(r.region)}
                      </div>
                    </td>
                    <td className="td text-xs text-slate-600" data-m="hide">{r.plan_id ?? (r.type === 'volume' ? `${r.disk_gb} GB` : '—')}</td>
                    <td className="td num text-right" data-m="end"><span className="label mr-1 lg:hidden">CPU p95</span>{formatPct(r.stats?.cpu_p95)}</td>
                    <td className="td num text-right" data-m="hide">{formatPct(r.stats?.cpu_p99)}</td>
                    <td className="td num text-right" data-m="end"><span className="label mr-1 lg:hidden">Mem p95</span>{formatPct(r.stats?.mem_p95)}</td>
                    <td className="td num text-right" data-m="hide">{formatPct(r.stats?.mem_p99)}</td>
                    <td data-m="hide" className={clsx('td num text-right', r.stats?.coverage != null && r.stats.coverage < 0.8 && 'font-semibold text-danger-700')}>
                      {r.stats?.coverage != null ? formatPct(r.stats.coverage * 100, 0) : '—'}
                    </td>
                    <td className="td" data-m="full">
                      {r.daily_p95 ? <Sparkline values={r.daily_p95} label={`${r.name} daily p95`} color={r.type === 'vm' ? SERIES[0] : SERIES[1]} /> : <span className="text-2xs text-slate-500">{r.type === 'ip' ? 'no metrics (IP)' : 'no metrics'}</span>}
                    </td>
                    <td className="td" data-m="full">{rec && <VerdictBadge verdict={rec.verdict} label={REASON_LABEL[rec.reason_code]} />}</td>
                    <td className="td num text-right text-slate-700" data-m="aside">{formatINR(r.monthly_inr)}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
          {!rows.length && <Empty hint="Clear a filter to see the full fleet.">No resources match these filters</Empty>}
        </div>
      ) : (
        <Panel title="Daily p95 CPU per VM" sub="IST days, darker is busier. Click a row to drill down. Blank cells are days with no data.">
          {heatRows.length ? <FleetHeatmap rows={heatRows} start={meta.data!.data_window.start} onPick={(id) => navigate(`/utilization/${id}`)} /> : <Empty hint="Clear a filter to bring VMs back.">No VMs with metrics match these filters</Empty>}
        </Panel>
      )}
    </Page>
  )
}
