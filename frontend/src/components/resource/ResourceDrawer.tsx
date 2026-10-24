import { useEffect, useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import clsx from 'clsx'
import { AlertTriangle, Bell, CheckCircle2, ExternalLink, Flag, ShieldCheck, X, XCircle, MinusCircle, Info } from 'lucide-react'
import { useQuery } from '@tanstack/react-query'
import { useAlerts, useMetric, useReplay, useResourceDetail, useResources } from '../../api/data'
import { postFile } from '../../api/client'
import { useUi } from '../../store/ui'
import { useRecs } from '../../api/recs'
import { useResourceDrawer } from '../../lib/useDrawer'
import { formatDateTimeIST, formatINR, formatPct, titleCase } from '../../lib/format'
import { REASON_LABEL, optionLabel, titleEnv } from '../../lib/labels'
import { actionsOf } from '../../lib/cost'
import type { MetricName, MetricStats, Recommendation, Step, TraceStep } from '../../types/contract'
import { Badge, ErrorNote, Loading, RiskChip, Segmented, VerdictBadge } from '../common/ui'
import { DecideControl } from '../recs/DecideControl'
import { ReplayChart } from '../charts/ReplayChart'
import { TimeSeriesChart } from '../charts/TimeSeriesChart'
import { HourOfWeekHeatmap } from '../charts/HourOfWeekHeatmap'
import { SERIES } from '../charts/theme'
import { useDecisions } from '../../store/decisions'

const TABS = ['decision', 'charts', 'trace', 'script'] as const
type Tab = (typeof TABS)[number]

export function ResourceDrawer() {
  const { id, close } = useResourceDrawer()
  const recs = useRecs()
  const [params, setParams] = useSearchParams()
  const tab = (TABS.includes(params.get('tab') as Tab) ? params.get('tab') : 'decision') as Tab
  const r = useMemo(() => recs.data?.items.find((i) => i.resource.resource_id === id), [recs.data, id])

  useEffect(() => {
    if (!id) return
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && close()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [id, close])

  if (!id) return null
  const setTab = (t: Tab) =>
    setParams((p) => {
      const n = new URLSearchParams(p)
      n.set('tab', t)
      return n
    })

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      <div className="absolute inset-0 animate-fade-in bg-brand-950/40" onClick={close} aria-hidden />
      <aside
        role="dialog"
        aria-modal="true"
        aria-label={r ? `Resource ${r.resource.name}` : 'Resource'}
        className="relative flex h-full w-[min(780px,100vw)] animate-slide-in flex-col bg-white shadow-pop"
        data-testid="resource-drawer"
      >
        {!r ? (
          <div className="p-6">{recs.isLoading ? <Loading /> : <p className="text-sm text-slate-500">Unknown resource {id}.</p>}</div>
        ) : (
          <>
            <DrawerHeader r={r} onClose={close} />
            <div className="flex gap-1 overflow-x-auto border-b border-slate-200 px-3 sm:px-5" role="tablist">
              {TABS.map((t) => (
                <button
                  key={t}
                  role="tab"
                  aria-selected={tab === t}
                  onClick={() => setTab(t)}
                  className={clsx('-mb-px border-b-2 px-3 py-2.5 text-sm capitalize transition-colors duration-150', tab === t ? 'border-brand font-medium text-slate-900' : 'border-transparent text-slate-500 hover:text-slate-800')}
                >
                  {t}
                </button>
              ))}
            </div>
            <div className="flex-1 overflow-y-auto px-4 py-5 sm:px-5">
              {tab === 'decision' && <DecisionTab r={r} />}
              {tab === 'charts' && <ChartsTab r={r} />}
              {tab === 'trace' && <TraceTab r={r} />}
              {tab === 'script' && <ScriptTab r={r} />}
            </div>
            <DecisionBar r={r} />
          </>
        )}
      </aside>
    </div>
  )
}

/** The decision lives in one sticky place: what we recommend, what it saves, and the two buttons. */
function DecisionBar({ r }: { r: Recommendation }) {
  if (Object.keys(r.options).filter((k) => k !== 'none').length < 1) return null
  const o = r.options[r.default_option]
  return (
    <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 border-t border-slate-200 bg-white px-4 py-3 sm:px-5" data-testid="decision-bar">
      <div className="min-w-0 text-sm">
        <div className="font-medium text-slate-900">{optionLabel(r.default_option, r)}</div>
        <div className="num text-[13px] text-slate-600">
          {o.saving_inr >= 0 ? 'saves' : 'costs'} <span className={clsx('font-semibold', o.saving_inr >= 0 ? 'text-save-700' : 'text-upsize-700')}>{formatINR(Math.abs(o.saving_inr))}/mo</span> · {r.risk ? `${r.risk.level} risk` : 'no risk score'}
        </div>
      </div>
      <DecideControl r={r} />
    </div>
  )
}

function DrawerHeader({ r, onClose }: { r: Recommendation; onClose: () => void }) {
  const c = r.current
  const spec = r.resource.type === 'vm' ? `${c.plan ?? '—'} · ${c.vcpu ?? '—'} vCPU / ${c.ram_gb ?? '—'} GB · ${c.disk_gb ?? '—'} GB disk` : r.resource.type === 'volume' ? `${c.disk_gb} GB volume` : 'Public IP'
  return (
    <div className="border-b border-slate-200 px-4 py-4 sm:px-5">
      <div className="flex items-start gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="text-xl font-normal text-slate-900" style={{ letterSpacing: '-0.015em' }}>{r.resource.name}</h2>
            <VerdictBadge verdict={r.verdict} />
            <span className="text-xs text-slate-500">{REASON_LABEL[r.reason_code]}</span>
          </div>
          <div className="mt-1.5 text-xs leading-relaxed text-slate-500">
            {r.resource.resource_id} · {titleEnv(r.resource.env)} · {titleCase(r.resource.owner)} · {titleCase(r.resource.region)} · {spec} · {formatINR(c.monthly_inr)}/mo
            {r.resource.state && r.resource.state !== 'running' && <> · <span className="font-medium text-slate-700">{r.resource.state}</span></>}
          </div>
          {(r.flags.length > 0 || r.resource.tags.length > 0) && (
            <div className="mt-2 flex flex-wrap gap-1.5">
              {r.resource.tags.map((t) => (
                <span key={t} className="rounded-full bg-slate-100 px-2 py-0.5 font-mono text-2xs text-slate-600">
                  {t}
                </span>
              ))}
              {r.flags.map((f) => (
                <Badge key={f.code} tone="review" icon={<Flag size={11} aria-hidden />} className="whitespace-normal" title={f.code}>
                  {f.message}
                </Badge>
              ))}
            </div>
          )}
        </div>
        <button className="btn-ghost h-9 w-9 p-0" onClick={onClose} aria-label="Close">
          <X size={18} />
        </button>
      </div>
    </div>
  )
}

const CALLOUT = {
  recommend: 'border-save-600/30 bg-save-50 text-save-700',
  upsize: 'border-upsize-600/30 bg-upsize-50 text-upsize-700',
  reject: 'border-kept-600/30 bg-kept-50 text-kept-700',
  flag: 'border-review-600/30 bg-review-50 text-review-700',
  exclude: 'border-slate-300 bg-slate-50 text-slate-700',
  healthy: 'border-healthy-600/30 bg-healthy-50 text-healthy-700',
}

function DecisionTab({ r }: { r: Recommendation }) {
  const alerts = useAlerts()
  const linked = alerts.data?.items.filter((a) => r.alert_ids.includes(a.alert_id)) ?? []
  const naive = r.evidence.naive
  const choices = Object.keys(r.options)

  return (
    <div className="space-y-5">
      <div className={clsx('rounded-lg border px-4 py-3 text-sm', CALLOUT[r.verdict])} data-testid="drawer-reason">
        <div className="flex gap-2">
          {r.verdict === 'reject' ? <ShieldCheck size={18} className="mt-0.5 shrink-0" /> : <Info size={18} className="mt-0.5 shrink-0" />}
          <p className="leading-relaxed">{r.reason}</p>
        </div>
      </div>

      {naive && naive.action !== 'none' && (
        <div className="rounded-lg border border-dashed border-slate-300 px-4 py-3 text-sm" data-testid="naive-box">
          <div className="label mb-1">An average-based tool would have…</div>
          <p className="text-slate-700">
            {naive.action === 'resize' ? `Resized ${r.current.plan} → ${naive.target_plan}` : titleCase(naive.action)} because {naive.basis}, saving{' '}
            <span className="num font-semibold">{formatINR(naive.saving_inr)}/month</span>.
            {naive.replay_minutes_above_90 !== null && (
              <>
                {' '}Peak Replay of that change: <span className="num font-semibold text-danger-700">{naive.replay_minutes_above_90.toLocaleString('en-IN')} min above 90% CPU</span> in 30 days.
              </>
            )}{' '}
            <span className="font-medium text-kept-700">We kept it.</span>
          </p>
        </div>
      )}

      {r.veto && (
        <div className="grid gap-3 text-sm sm:grid-cols-3" data-testid="veto">
          <Fact label="Vetoing signal" value={titleCase(r.veto.signal)} />
          <Fact label={r.veto.metric} value={typeof r.veto.value === 'number' ? r.veto.value.toLocaleString('en-IN', { maximumFractionDigits: 1 }) : String(r.veto.value)} />
          <Fact label="Rule" value={`${r.veto.comparator} ${r.veto.threshold} blocks shrinking`} />
        </div>
      )}

      {choices.length > 1 && <OptionsTable r={r} />}

      {r.schedule && (
        <section>
          <h3 className="h-sec mb-2">Schedule (IST)</h3>
          <div className="text-sm text-slate-700">
            Off <span className="num font-semibold">{r.schedule.off_hours_per_week} h/week</span>, on {r.schedule.on_hours_per_week} h/week:
            <ul className="mt-1 list-inside list-disc text-slate-600" data-testid="schedule-windows">
              {r.schedule.windows.map((w, i) => (
                <li key={i}>
                  {w.days.includes('→') ? `${w.days.split(' → ')[0]} ${w.start} → ${w.days.split(' → ')[1]} ${w.end}` : `${w.days} ${w.start}–${w.end}`}
                </li>
              ))}
            </ul>
            {r.schedule.busy_hours_excluded.length > 0 && (
              <p className="mt-1 text-xs text-slate-500">Kept on: {r.schedule.busy_hours_excluded.join(', ')} (busy in every week).</p>
            )}
          </div>
        </section>
      )}

      {r.risk && (
        <section>
          <h3 className="h-sec mb-2 flex flex-wrap items-center gap-2">
            Risk <RiskChip risk={r.risk} /> <span className="text-xs font-normal text-slate-500">confidence {r.risk.confidence}: {r.risk.confidence_basis}</span>
          </h3>
          <div className="flex flex-wrap gap-1.5">
            {r.risk.points.map((p) => (
              <span key={p.factor} className="rounded-full bg-slate-100 px-2.5 py-0.5 text-2xs text-slate-700">
                +{p.points} {p.factor} <span className="text-slate-500">· {p.detail}</span>
              </span>
            ))}
          </div>
        </section>
      )}

      <EvidenceTable r={r} />

      <ReplaySection r={r} />

      {r.actions.length > 0 && (
        <section>
          <h3 className="h-sec mb-2">Runbook</h3>
          <ol className="space-y-1.5 text-sm">
            {r.actions.map((a, i) => (
              <li key={a.type} className="flex gap-2">
                <span className="num flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-slate-100 text-2xs font-semibold text-slate-600">{i + 1}</span>
                <span className="text-slate-700">
                  {a.description}
                  <span className="text-xs text-slate-500"> · rollback: {a.rollback}{a.reversible ? '' : ' (not reversible after the hold)'}</span>
                </span>
              </li>
            ))}
          </ol>
        </section>
      )}

      {linked.length > 0 && (
        <section>
          <h3 className="h-sec mb-2">Alerts</h3>
          {linked.map((a) => (
            <Link key={a.alert_id} to={`/alerts#${a.alert_id}`} className="flex items-center gap-2 text-sm text-sky-700 hover:underline">
              <Bell size={14} /> {a.title} <ExternalLink size={12} />
            </Link>
          ))}
        </section>
      )}
    </div>
  )
}

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg bg-slate-50 px-3 py-2">
      <div className="label">{label}</div>
      <div className="num mt-0.5 font-semibold text-slate-900">{value}</div>
    </div>
  )
}

function OptionsTable({ r }: { r: Recommendation }) {
  const decision = useDecisions((s) => s.decisions[r.resource.resource_id])
  const applied = decision?.status === 'accepted' ? decision.optionKey : null
  return (
    <section>
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <h3 className="h-sec">Options: cost after, per combination (never added together)</h3>
      </div>
      <table className="w-full text-sm" data-testid="options-table">
        <thead>
          <tr className="border-b border-slate-200">
            <th className="th pl-0">Option</th>
            <th className="th text-right">After / mo</th>
            <th className="th text-right">Saving</th>
          </tr>
        </thead>
        <tbody>
          {Object.entries(r.options).map(([k, o]) => (
            <tr key={k} className={clsx('border-b border-slate-100 align-top', applied === k && 'bg-save-50')} data-testid={`option-${k}`}>
              <td className="py-2 pr-3">
                <div className="font-medium text-slate-800">
                  {optionLabel(k, r)}
                  {k === r.default_option && k !== 'none' && <span className="ml-1.5 text-2xs font-normal text-slate-500">default</span>}
                  {applied === k && <CheckCircle2 size={13} className="ml-1 inline text-save-600" />}
                </div>
                <div className="mt-0.5 font-mono text-2xs leading-relaxed text-slate-500" data-testid="formula">{o.formula}</div>
              </td>
              <td className="num py-2 text-right text-slate-700">{formatINR(o.monthly_inr_after)}</td>
              <td className={clsx('num py-2 text-right font-semibold', o.saving_inr > 0 ? 'text-save-700' : o.saving_inr < 0 ? 'text-upsize-700' : 'text-slate-500')}>
                {formatINR(o.saving_inr)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  )
}

/** Whether the backend has a metrics series for this resource (so we never request one it doesn't). */
function useHasMetrics(resourceId: string) {
  const resources = useResources()
  return !!resources.data?.find((x) => x.resource_id === resourceId)?.has_metrics
}

function ReplaySection({ r }: { r: Recommendation }) {
  const preset = useUi((s) => s.preset)
  const hasMetrics = useHasMetrics(r.resource.resource_id)
  const show = !!r.replay && r.resource.type === 'vm' && hasMetrics
  const replay = useReplay(show ? r.resource.resource_id : null, preset)
  if (!r.replay || r.resource.type !== 'vm') return null
  return (
    <section data-testid="replay-section">
      <div className="mb-1.5 flex flex-wrap items-baseline justify-between gap-x-3">
        <h3 className="h-sec">Peak Replay</h3>
        <span className="text-2xs text-slate-500">
          30 days replayed on the new size · limit {r.replay.limit_minutes_above_90} min &gt; 90%, memory ≤ {r.replay.mem_cap_pct}%
        </span>
      </div>
      <div className="mb-2 flex flex-wrap gap-1.5" data-testid="replay-attempts">
        {r.replay.attempts.map((a) => (
          <Badge key={a.plan} tone={a.passed ? 'save' : 'danger'} icon={a.passed ? <CheckCircle2 size={12} aria-hidden /> : <XCircle size={12} aria-hidden />} className="whitespace-normal">
            {a.plan}: {a.minutes_above_90.toLocaleString('en-IN')} min &gt; 90% · peak {a.max_cpu_pct}% CPU / {a.max_mem_pct}% mem
          </Badge>
        ))}
      </div>
      {!show ? null : replay.error ? <ErrorNote error={replay.error} /> : replay.data ? <ReplayChart replay={replay.data} /> : <Loading label="Loading replay…" block />}
    </section>
  )
}

const STAT_ROWS: [keyof NonNullable<Recommendation['evidence']['metrics']>, string][] = [
  ['cpu', 'CPU %'], ['mem', 'Memory %'], ['iops_pct', 'IOPS % of provisioned'], ['net_pct', 'Network % of bandwidth'], ['disk_used', 'Disk used %'],
]

export function EvidenceTable({ r }: { r: Recommendation }) {
  const m = r.evidence.metrics
  const ev = r.evidence
  return (
    <section>
      <h3 className="h-sec mb-2">
        Evidence <span className="text-xs font-normal text-slate-500">· {ev.days_of_data} days of data · coverage {formatPct(ev.coverage * 100, 0)} · percentile used {ev.percentile_used}</span>
      </h3>
      {!m ? (
        <p className="text-sm text-slate-500">No usable metrics for this resource.</p>
      ) : (
        <div className="overflow-x-auto"><table className="w-full text-sm" data-testid="evidence-table">
          <thead>
            <tr className="border-b border-slate-200">
              <th className="th pl-0">Metric</th>
              {['mean', 'p50', 'p95', 'p99', 'max'].map((h) => (
                <th key={h} className="th text-right">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {STAT_ROWS.filter(([k]) => m[k]).map(([k, label]) => {
              const s = m[k] as MetricStats
              return (
                <tr key={k} className="border-b border-slate-100">
                  <td className="py-1.5 text-slate-700">{label}</td>
                  {(['mean', 'p50', 'p95', 'p99', 'max'] as const).map((q) => (
                    <td key={q} className="num py-1.5 text-right text-slate-800">{s[q].toFixed(1)}</td>
                  ))}
                </tr>
              )
            })}
          </tbody>
        </table></div>
      )}
      {ev.recurring_peak && (
        <p className="mt-2 text-xs text-slate-600">
          Recurring peak: {ev.recurring_peak.window_ist} on {ev.recurring_peak.days} of 30 days.
        </p>
      )}
    </section>
  )
}

export function ChartsTab({ r }: { r: Recommendation }) {
  const alerts = useAlerts()
  const hasMetrics = useHasMetrics(r.resource.resource_id)
  const id = hasMetrics ? r.resource.resource_id : null
  const detail = useResourceDetail(id)
  const [step, setStep] = useState<Step>('1h')
  const first = useMetric(id, r.resource.type === 'vm' ? 'cpu' : 'disk_used', step)
  const bands = useMemo(
    () => (alerts.data?.items ?? []).filter((a) => r.alert_ids.includes(a.alert_id) && a.window && a.type !== 'capacity' && a.type !== 'memory_leak').map((a) => ({ start: a.window!.start, end: a.window!.end, label: a.title, tone: 'alert' as const })),
    [alerts.data, r.alert_ids],
  )
  if (r.resource.type === 'ip') return <p className="text-sm text-slate-500">Public IPs have no metrics.</p>
  if (!hasMetrics) return <p className="text-sm text-slate-500" data-testid="no-metrics">No metrics: {REASON_LABEL[r.reason_code]}.</p>
  const ev = r.evidence.metrics
  const gaps = first.data?.gaps ?? []
  const group = `res-${r.resource.resource_id}`
  const common = { id: r.resource.resource_id, step, group }
  return (
    <div className="space-y-4" data-testid="charts-tab">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="max-w-[60ch] text-xs leading-relaxed text-slate-500">IST. Shaded bands are gaps (missing ≠ 0) or alert windows; dotted lines are the p50 / p95 / p99 from the engine. Scroll to zoom; the charts move together.</p>
        <Segmented label="Resolution" value={step} onChange={setStep} options={[{ value: '1h', label: 'Hourly' }, { value: '5m', label: '5-minute' }]} />
      </div>
      {gaps.length > 0 && (
        <div className="rounded-lg bg-slate-50 px-3 py-2 text-xs text-slate-600" data-testid="gap-list">
          <span className="font-semibold text-slate-700">{gaps.length} gap{gaps.length > 1 ? 's' : ''} ≥ 30 min, kept as missing (never 0):</span>{' '}
          {gaps.slice(0, 4).map((g) => `${formatDateTimeIST(g.start)} for ${g.hours} h${g.kind === 'flatline' ? ' (stuck agent)' : ''}`).join(' · ')}
          {gaps.length > 4 && ` · +${gaps.length - 4} more`}
        </div>
      )}
      {r.resource.type === 'vm' ? (
        <>
          <MetricChart {...common} title="CPU" metric="cpu" color={SERIES[0]} threshold={{ value: 90, label: '90%' }} percentiles={ev?.cpu} bands={bands} testId="chart-cpu" yMax={100} />
          <MetricChart {...common} title="Memory" metric="mem" color={SERIES[6]} threshold={{ value: 70, label: 'veto 70%' }} percentiles={ev?.mem} testId="chart-mem" yMax={100} />
          <MetricChart {...common} title="Network out (Mbps)" metric="net_out" unit=" Mbps" color={SERIES[2]} testId="chart-net" height={160} />
          <MetricChart {...common} title="Disk used" metric="disk_used" color={SERIES[1]} percentiles={ev?.disk_used} testId="chart-disk" height={160} yMax={100} />
          {detail.data?.features?.how_p95 && (
            <ChartBlock title="p95 CPU by hour of week (IST)">
              <HourOfWeekHeatmap values={detail.data.features.how_p95} />
            </ChartBlock>
          )}
        </>
      ) : (
        <>
          <MetricChart {...common} title="IOPS" metric="iops" unit="" color={SERIES[0]} testId="chart-iops" />
          <MetricChart {...common} title="Disk used" metric="disk_used" color={SERIES[1]} threshold={{ value: 90, label: '90%' }} percentiles={ev?.disk_used} testId="chart-disk" yMax={100} />
        </>
      )}
    </div>
  )
}

function MetricChart({ id, metric, step, title, testId, ...rest }: { id: string; metric: MetricName; step: Step; title: string; testId: string } & Omit<React.ComponentProps<typeof TimeSeriesChart>, 'series' | 'label' | 'testId'>) {
  const q = useMetric(id, metric, step)
  const p = rest.percentiles
  return (
    <ChartBlock
      title={title}
      note={p ? <span data-testid={`${testId}-percentiles`}>dotted: p50 {p.p50.toFixed(1)} · p95 {p.p95.toFixed(1)} · p99 {p.p99.toFixed(1)}</span> : undefined}
    >
      {q.error ? <ErrorNote error={q.error} /> : q.data ? <TimeSeriesChart series={q.data} label={title.replace(/ (.*)$/, '')} testId={testId} {...rest} /> : <Loading label={`Loading ${title}…`} block />}
    </ChartBlock>
  )
}

function ChartBlock({ title, note, children }: { title: string; note?: React.ReactNode; children: React.ReactNode }) {
  return (
    <section>
      <h3 className="h-sec mb-1 flex flex-wrap items-baseline gap-x-2">
        {title}
        {note && <span className="num text-2xs font-normal text-slate-500">{note}</span>}
      </h3>
      {children}
    </section>
  )
}

export function TraceTab({ r }: { r: Recommendation }) {
  return (
    <div>
      <TraceList steps={r.trace} />
      {actionsOf(r.default_option).length > 0 && <p className="mt-3 text-xs text-slate-500">Formula: <span className="font-mono">{r.formula}</span></p>}
    </div>
  )
}

export function TraceList({ steps }: { steps: TraceStep[] }) {
  const icon = {
    pass: <CheckCircle2 size={15} className="text-save-600" />,
    fail: <XCircle size={15} className="text-danger-600" />,
    info: <Info size={15} className="text-slate-400" />,
    skip: <MinusCircle size={15} className="text-slate-300" />,
  }
  return (
    <div data-testid="trace">
      <p className="mb-3 text-xs text-slate-500">Every resource goes through the same ordered checks. The first terminal check decides; later checks are skipped. Comparisons are strict.</p>
      <ol className="space-y-0.5">
        {steps.map((s) => (
          <li
            key={s.step}
            className={clsx('grid grid-cols-[20px_1fr_auto] items-start gap-2 rounded-lg px-2 py-1.5 text-sm', s.terminal && 'bg-brand-900 text-white', s.result === 'skip' && 'opacity-50')}
            data-testid={s.terminal ? 'trace-terminal' : undefined}
          >
            <span className="mt-0.5">{s.terminal && s.result === 'fail' ? <AlertTriangle size={15} className="text-review-100" /> : icon[s.result]}</span>
            <span>
              <span className={clsx('font-mono text-2xs', s.terminal ? 'text-slate-300' : 'text-slate-500')}>{s.step}</span>
              <span className="ml-2">{s.check}</span>
            </span>
            <span className={clsx('num text-right text-xs', s.terminal ? 'text-white' : 'text-slate-600')}>
              {s.value} <span className={s.terminal ? 'text-slate-300' : 'text-slate-500'}>· rule {s.threshold}</span>
            </span>
          </li>
        ))}
      </ol>
    </div>
  )
}

/** The apply script for this one change, generated by the backend (POST /api/export) so it matches the bulk export exactly. */
function ScriptTab({ r }: { r: Recommendation }) {
  const decision = useDecisions((s) => s.decisions[r.resource.resource_id])
  const key = decision?.status === 'accepted' ? decision.optionKey : r.default_option
  const [format, setFormat] = useState<'sh' | 'tf'>('sh')
  const script = useQuery({
    queryKey: ['script', r.rec_id, key, format],
    queryFn: async () => (await postFile('/export', { accepted: [{ rec_id: r.rec_id, option_key: key }], format })).blob.text(),
    enabled: key !== 'none',
    staleTime: Infinity,
  })
  const [copied, setCopied] = useState(false)
  if (key === 'none') return <p className="text-sm text-slate-500">Nothing to apply: this resource has no recommended change.</p>
  return (
    <div className="space-y-3" data-testid="script-tab">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-xs text-slate-500">
          {optionLabel(key, r)}{decision?.status === 'accepted' ? ' (your accepted option)' : ' (default option)'}. Dry run by default; review before applying.
        </p>
        <div className="flex items-center gap-2">
          <Segmented label="Script format" value={format} onChange={setFormat} options={[{ value: 'sh', label: 'apply.sh' }, { value: 'tf', label: 'Terraform' }]} />
          <button
            className="btn-outline btn-sm"
            disabled={!script.data}
            onClick={() => {
              void navigator.clipboard?.writeText(script.data ?? '')
              setCopied(true)
              setTimeout(() => setCopied(false), 1500)
            }}
          >
            {copied ? 'Copied' : 'Copy'}
          </button>
        </div>
      </div>
      {script.error ? (
        <ErrorNote error={script.error} />
      ) : script.data === undefined ? (
        <Loading label="Generating script…" block />
      ) : (
        <pre className="max-h-[60vh] overflow-auto rounded-lg bg-brand-900 p-3 font-mono text-xs leading-relaxed text-slate-100" data-testid="script-text">
          {script.data}
        </pre>
      )}
    </div>
  )
}
