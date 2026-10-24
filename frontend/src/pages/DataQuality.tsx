import { useMemo, useState } from 'react'
import clsx from 'clsx'
import { CheckCircle2, XCircle } from 'lucide-react'
import { Page } from '../components/layout/AppShell'
import { Badge, ErrorNote, Loading, Stat, StatRow } from '../components/common/ui'
import { useDataQuality } from '../api/data'
import { formatNum, formatPct } from '../lib/format'
import { useResourceDrawer } from '../lib/useDrawer'
import type { DqRow } from '../types/api'

export default function DataQuality() {
  const dq = useDataQuality()
  const drawer = useResourceDrawer()
  const [all, setAll] = useState(false)
  const rows = dq.data?.checks ?? []
  const coverage = useMemo(
    () => [...(dq.data?.resources ?? [])].filter((r) => r.type === 'vm' && r.coverage !== null).sort((a, b) => (a.coverage ?? 0) - (b.coverage ?? 0)),
    [dq.data],
  )

  if (dq.isLoading) return <Page title="Data quality"><Loading /></Page>
  if (!dq.data) return <Page title="Data quality"><ErrorNote error={dq.error} /></Page>
  const t = dq.data.totals

  return (
    <Page title="Data quality" subtitle="Real monitoring data is dirty, so ours is too. Every fault is cleaned before any decision; missing data stays missing, never zero.">
      <StatRow className="md:grid-cols-3 lg:grid-cols-6">
        <Stat label="Rows ingested" value={formatNum(t.metric_rows)} sub="5-minute VM samples" how="Rows in metrics.parquet before cleaning (GET /api/data-quality totals.metric_rows)." testId="dq-rows" />
        <Stat label="Duplicates removed" value={t.duplicates} sub="agent re-sends" how="Rows sharing (resource, timestamp) after snapping; the first is kept, the rest dropped." testId="dq-dupes" />
        <Stat label="Out-of-range dropped" value={t.out_of_range} sub="CPU < 0% or > 100%" how="Percentages outside 0–100 and negative rates are set to missing, never clipped." testId="dq-oor" />
        <Stat label="Out-of-order sorted" value={t.out_of_order} sub="inversions" how="Count of rows whose timestamp is earlier than the row before; the series is sorted before use." testId="dq-ooo" />
        <Stat label="Timestamps snapped" value={t.irregular_ts} sub="to the 5-min grid" how="Timestamps not on a 5-minute boundary (e.g. 05:03) are floored to it." testId="dq-jitter" />
        <Stat label="Stuck-agent hours" value={formatNum(t.flatline_slots / 12, 0)} sub="treated as missing" testId="dq-flat" />
      </StatRow>

      <section className="card mb-4 overflow-clip">
        <div className="border-b border-slate-100 px-4 py-3">
          <h2 className="h-sec">Injected vs detected</h2>
          <p className="text-xs text-slate-500">The generator logs every fault it plants; the cleaning step must find each one.</p>
        </div>
        <table className="tbl tbl-stack" data-testid="dq-reconcile">
          <thead>
            <tr>
              <th className="th">Case</th>
              <th className="th">Fault</th>
              <th className="th">Where</th>
              <th className="th">Injected</th>
              <th className="th">Detected</th>
              <th className="th">Handling</th>
              <th className="th" />
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id} data-testid={`dq-${r.id}`}>
                <td className="td font-mono text-xs text-slate-500" data-m="hide">{r.id}</td>
                <td className="td font-medium text-slate-800" data-m="main">{r.fault}</td>
                <td className="td max-w-[220px] truncate text-xs text-slate-600 max-md:max-w-none" title={r.where} data-m="full">{r.where}</td>
                <td className="td num text-xs text-slate-600"><span className="label mr-1 md:hidden">Injected</span>{r.injected}</td>
                <td className="td num text-xs font-semibold text-slate-800" data-m="end"><span className="label mr-1 font-normal md:hidden">Detected</span>{r.detected}</td>
                <td className="td text-xs leading-relaxed text-slate-600" data-m="full">{r.handling}</td>
                <td className="td" data-m="aside">
                  {r.ok ? (
                    <Badge tone="save" icon={<CheckCircle2 size={12} aria-hidden />} data-testid="dq-ok">handled</Badge>
                  ) : (
                    <Badge tone="danger" icon={<XCircle size={12} aria-hidden />}>mismatch</Badge>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <div className="grid gap-4 lg:grid-cols-3">
        <section className="card p-4">
          <h2 className="h-sec mb-3">Inventory reconciliation</h2>
          <div className="label mb-1">Metrics but no inventory row</div>
          <ul className="mb-3 text-sm" data-testid="dq-ghost">
            {dq.data.not_in_inventory.map((x) => (
              <li key={x.resource_id} className="text-slate-700">
                <span className="font-mono text-xs">{x.resource_id}</span> {x.name}: possibly untracked or unbilled
              </li>
            ))}
          </ul>
          <div className="label mb-1">Inventory but no metrics</div>
          <ul className="text-sm" data-testid="dq-nometrics">
            {dq.data.no_metrics.map((x) => (
              <li key={x.resource_id}>
                <button className="text-sky-700 hover:underline" onClick={() => drawer.open(x.resource_id)}>{x.name}</button>
                <span className="text-xs text-slate-500"> · {x.state === 'stopped' ? 'stopped, expected' : 'running: monitoring missing'}</span>
              </li>
            ))}
          </ul>
        </section>

        <section className="card overflow-clip lg:col-span-2">
          <div className="flex items-center justify-between border-b border-slate-100 px-4 py-3">
            <h2 className="h-sec">Coverage by VM (worst first)</h2>
            <span className="text-2xs text-slate-500">gate: &lt; 80% excluded · 80–95% medium confidence</span>
          </div>
          <table className="tbl tbl-stack" data-testid="dq-coverage">
            <thead>
              <tr>
                <th className="th">VM</th>
                <th className="th">Coverage</th>
                <th className="th text-right">Worst hour-of-week</th>
                <th className="th text-right">Longest gap</th>
                <th className="th text-right">Days</th>
              </tr>
            </thead>
            <tbody>
              {(all ? coverage : coverage.slice(0, 10)).map((r) => (
                <CoverageRow key={r.resource_id} r={r} onOpen={() => r.in_inventory && drawer.open(r.resource_id)} />
              ))}
            </tbody>
          </table>
          <button className="w-full border-t border-slate-100 py-2.5 text-xs font-medium text-sky-700 transition-colors hover:bg-slate-50" onClick={() => setAll(!all)}>
            {all ? 'Show worst 10' : `Show all ${coverage.length}`}
          </button>
        </section>
      </div>
    </Page>
  )
}

function CoverageRow({ r, onOpen }: { r: DqRow; onOpen: () => void }) {
  const c = (r.coverage ?? 0) * 100
  const tone = c < 80 ? 'bg-danger-600' : c < 95 ? 'bg-review-600' : 'bg-save-600'
  return (
    <tr className="row-link" onClick={onOpen} data-testid={`cov-${r.name}`}>
      <td className="td font-medium text-slate-800" data-m="main">{r.name}</td>
      <td className="td" data-m="aside">
        <div className="flex items-center gap-2">
          <div className="h-2 w-28 overflow-hidden rounded-full bg-slate-100">
            <div className={clsx('h-2 rounded-full', tone)} style={{ width: `${c}%` }} />
          </div>
          <span className="num text-xs text-slate-700">{formatPct(c)}</span>
        </div>
      </td>
      <td data-m="hide" className="td num text-right text-xs">{r.peak_window_coverage !== null ? formatPct(r.peak_window_coverage * 100, 0) : '—'}</td>
      <td data-m="hide" className="td num text-right text-xs">{r.longest_gap_hours ? `${r.longest_gap_hours} h` : '—'}</td>
      <td data-m="hide" className="td num text-right text-xs">{r.days_of_data ?? '—'}</td>
    </tr>
  )
}
