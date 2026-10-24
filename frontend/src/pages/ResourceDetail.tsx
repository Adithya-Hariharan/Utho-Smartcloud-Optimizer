import { Link, useParams } from 'react-router-dom'
import { ArrowLeft, PanelRightOpen } from 'lucide-react'
import { Page } from '../components/layout/AppShell'
import { ErrorNote, Loading, VerdictBadge } from '../components/common/ui'
import { ChartsTab, EvidenceTable, TraceList } from '../components/resource/ResourceDrawer'
import { useResourceDetail } from '../api/data'
import { useRecs } from '../api/recs'
import { ApiError } from '../api/client'
import { useResourceDrawer } from '../lib/useDrawer'
import { formatINR, formatNum, formatPct, titleCase } from '../lib/format'
import { REASON_LABEL, titleEnv } from '../lib/labels'
import type { ResourceDetail as Detail } from '../types/contract'

/** Full-page drill-down: 30 days of every metric, engine features, data-quality report and the decision trace (GET /api/resources/{id}). */
export default function ResourceDetail() {
  const { id } = useParams()
  const detail = useResourceDetail(id ?? null)
  const recs = useRecs()
  const drawer = useResourceDrawer()
  const r = recs.data?.items.find((i) => i.resource.resource_id === id)

  if (detail.error instanceof ApiError && detail.error.status === 404)
    return (
      <Page title="Resource not found" subtitle={`No resource with id ${id}.`}>
        <Link to="/utilization" className="btn-outline">
          <ArrowLeft size={14} /> Back to Utilization
        </Link>
      </Page>
    )
  if (detail.isLoading || recs.isLoading) return <Page title="Resource"><Loading /></Page>
  if (!detail.data || !recs.data) return <Page title="Resource"><ErrorNote error={detail.error ?? recs.error} /></Page>
  const d = detail.data
  const res = d.resource

  return (
    <Page
      title={res.name}
      subtitle={
        <span className="flex flex-wrap items-center gap-2">
          {r && <VerdictBadge verdict={r.verdict} label={REASON_LABEL[r.reason_code]} />}
          {res.resource_id} · {titleEnv(res.env)} · {titleCase(res.owner_team ?? 'unowned')} · {titleCase(res.region)} · {res.plan_id ?? res.type.toUpperCase()} · {formatINR(res.monthly_inr)}/mo
        </span>
      }
      actions={
        <>
          <Link to="/utilization" className="btn-ghost">
            <ArrowLeft size={14} /> Utilization
          </Link>
          <button className="btn-primary" onClick={() => drawer.open(res.resource_id)}>
            <PanelRightOpen size={14} /> Open decision
          </button>
        </>
      }
    >
      <div className="grid grid-cols-5 gap-4">
        <div className="card card-pad col-span-3">{r ? <ChartsTab r={r} /> : <p className="text-sm text-slate-500">No recommendation for this resource.</p>}</div>
        <div className="col-span-2 space-y-4">
          {r && (
            <div className="card card-pad">
              <p className="mb-3 text-sm text-slate-700">{r.reason}</p>
              <EvidenceTable r={r} />
            </div>
          )}
          <Features d={d} />
          <DqReport d={d} />
          <div className="card card-pad">
            <h3 className="mb-2 text-sm font-semibold text-slate-800">Decision trace (Default preset)</h3>
            <TraceList steps={d.trace} />
          </div>
        </div>
      </div>
    </Page>
  )
}

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex justify-between gap-3 border-b border-slate-100 py-1 text-sm last:border-0">
      <span className="text-slate-600">{label}</span>
      <span className="num text-right text-slate-900">{value}</span>
    </div>
  )
}

function Features({ d }: { d: Detail }) {
  const f = d.features
  if (!f) return null
  return (
    <div className="card card-pad" data-testid="features">
      <h3 className="mb-2 text-sm font-semibold text-slate-800">Engine features</h3>
      {f.cpu_slope != null && <Row label="CPU daily-p95 trend" value={`${f.cpu_slope >= 0 ? '+' : ''}${f.cpu_slope.toFixed(2)} pts/day`} />}
      {f.disk_slope != null && <Row label="Disk used trend" value={`${f.disk_slope >= 0 ? '+' : ''}${f.disk_slope.toFixed(2)} pts/day`} />}
      {f.level_shift_up != null && <Row label="Last 48 h ÷ prior mean" value={`${f.level_shift_up.toFixed(2)}×`} />}
      {f.level_shift_down != null && <Row label="Last 7 d ÷ prior 23 d" value={`${f.level_shift_down.toFixed(2)}×`} />}
      {f.recurring_peak_days != null && <Row label="Days with a 30-min peak > 80%" value={`${f.recurring_peak_days}${f.recurring_window ? ` · ${f.recurring_window}` : ''}`} />}
      {f.p99_excl_top_day != null && <Row label="CPU p99 without the busiest day" value={formatPct(f.p99_excl_top_day)} />}
      {f.leak_cycles != null && <Row label="Memory sawtooth cycles" value={f.leak_cycles} />}
      {f.mem_std != null && <Row label="Memory std-dev" value={formatNum(f.mem_std, 1)} />}
    </div>
  )
}

function DqReport({ d }: { d: Detail }) {
  const q = d.dq
  if (!q) return null
  return (
    <div className="card card-pad" data-testid="dq-report">
      <h3 className="mb-2 text-sm font-semibold text-slate-800">Data-quality report</h3>
      <Row label="Coverage" value={q.coverage != null ? formatPct(q.coverage * 100) : '—'} />
      <Row label="Worst hour-of-week coverage" value={q.peak_window_coverage != null ? formatPct(q.peak_window_coverage * 100, 0) : '—'} />
      <Row label="Days of data" value={q.days_of_data ?? '—'} />
      <Row label="Gaps ≥ 30 min · longest" value={`${q.gaps} · ${q.longest_gap_hours ? `${q.longest_gap_hours} h` : '—'}`} />
      <Row label="Duplicates removed" value={q.duplicates} />
      <Row label="Out-of-range dropped" value={q.out_of_range} />
      <Row label="Out-of-order rows sorted" value={q.out_of_order} />
      <Row label="Timestamps snapped" value={q.irregular_ts} />
      <Row label="Stuck-agent slots → missing" value={q.flatline_slots} />
    </div>
  )
}
