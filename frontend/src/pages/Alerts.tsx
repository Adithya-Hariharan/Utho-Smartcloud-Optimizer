import { useEffect, useMemo } from 'react'
import { useLocation } from 'react-router-dom'
import clsx from 'clsx'
import { AlertOctagon, AlertTriangle, Info, Lightbulb } from 'lucide-react'
import { Page } from '../components/layout/AppShell'
import { FilterBar, useUrlFilters } from '../components/common/FilterBar'
import { Empty, ErrorNote, Loading } from '../components/common/ui'
import { TimeSeriesChart } from '../components/charts/TimeSeriesChart'
import { SERIES } from '../components/charts/theme'
import { useAlerts, useMetric, useResources } from '../api/data'
import type { MetricName } from '../types/contract'
import { formatDateTimeIST, titleCase } from '../lib/format'
import { useResourceDrawer } from '../lib/useDrawer'
import type { Alert } from '../types/api'

// Status colours are reserved for severity and always paired with an icon and a word.
const SEV = {
  critical: { label: 'Critical', icon: AlertOctagon, cls: 'border-l-danger-600', chip: 'bg-danger-50 text-danger-700 ring-danger-600/25' },
  warning: { label: 'Warning', icon: AlertTriangle, cls: 'border-l-review-600', chip: 'bg-review-50 text-review-700 ring-review-600/25' },
  info: { label: 'Info', icon: Info, cls: 'border-l-slate-400', chip: 'bg-slate-100 text-slate-600 ring-slate-400/30' },
} as const

const METRIC_SERIES: Record<string, { metric: MetricName; label: string; color: string; unit?: string }> = {
  cpu_pct: { metric: 'cpu', label: 'CPU', color: SERIES[0] },
  cpu_p95_slope: { metric: 'cpu', label: 'CPU', color: SERIES[0] },
  cpu_p99: { metric: 'cpu', label: 'CPU', color: SERIES[0] },
  mem_pct: { metric: 'mem', label: 'Memory', color: SERIES[6] },
  disk_used_pct: { metric: 'disk_used', label: 'Disk used', color: SERIES[1] },
  net_out_mbps: { metric: 'net_out', label: 'Net out', color: SERIES[2], unit: ' Mbps' },
}

export default function Alerts() {
  const alerts = useAlerts()
  const filters = useUrlFilters(['severity', 'type', 'q'])
  const { hash } = useLocation()
  const items = alerts.data?.items ?? []
  const f = filters.values
  const shown = useMemo(
    () => items.filter((a) => (!f.severity || a.severity === f.severity) && (!f.type || a.type === f.type) && (!f.q || `${a.name} ${a.title}`.toLowerCase().includes(f.q.toLowerCase()))),
    [items, f],
  )

  useEffect(() => {
    if (hash && alerts.data) document.getElementById(hash.slice(1))?.scrollIntoView({ block: 'start' })
  }, [hash, alerts.data])

  if (alerts.isLoading) return <Page title="Alerts"><Loading /></Page>
  if (!alerts.data) return <Page title="Alerts"><ErrorNote error={alerts.error} /></Page>

  const count = (s: Alert['severity']) => items.filter((a) => a.severity === s).length

  return (
    <Page title="Alerts" subtitle="One alert per resource and type, each with the numbers behind it. Baselines are hour-of-week, so a batch at its usual hour never alerts.">
      <div className="mb-3 flex gap-2">
        {(['critical', 'warning', 'info'] as const).map((s) => {
          const Icon = SEV[s].icon
          return (
            <button
              key={s}
              onClick={() => filters.set('severity', f.severity === s ? '' : s)}
              aria-pressed={f.severity === s}
              className={clsx('inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-semibold ring-1 ring-inset', SEV[s].chip, f.severity && f.severity !== s && 'opacity-40')}
              data-testid={`sev-${s}`}
            >
              <Icon size={13} /> {SEV[s].label} <span className="num">{count(s)}</span>
            </button>
          )
        })}
      </div>
      <div className="mb-3">
        <FilterBar
          filters={filters}
          defs={[{ key: 'type', label: 'Type', options: [...new Set(items.map((a) => a.type))].sort().map((t) => ({ value: t, label: titleCase(t) })) }]}
        />
      </div>
      <div className="space-y-3" data-testid="alert-list">
        {shown.map((a) => (
          <AlertCard key={a.alert_id} a={a} />
        ))}
        {!shown.length && <Empty>No alerts match.</Empty>}
      </div>
    </Page>
  )
}

function AlertCard({ a }: { a: Alert }) {
  const drawer = useResourceDrawer()
  const s = SEV[a.severity]
  const Icon = s.icon
  const chart = METRIC_SERIES[a.evidence.metric]
  const resources = useResources()
  const hasMetrics = !!chart && !!resources.data?.find((r) => r.resource_id === a.resource_id)?.has_metrics
  const metrics = useMetric(hasMetrics ? a.resource_id : null, chart?.metric ?? 'cpu')
  const band = a.window && !['capacity', 'memory_leak', 'under_provisioned'].includes(a.type) ? [{ start: a.window.start, end: a.window.end, label: a.title, tone: 'alert' as const }] : []
  return (
    <article id={a.alert_id} className="card scroll-mt-4" data-testid={`alert-${a.type}-${a.name}`}>
      <div className="grid grid-cols-[1fr_380px] gap-4 p-4">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <span className={clsx('inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-2xs font-semibold ring-1 ring-inset', s.chip)}>
              <Icon size={12} /> {s.label}
            </span>
            <span className="font-mono text-2xs text-slate-400">{a.alert_id}</span>
            <span className="text-2xs text-slate-500">{titleCase(a.type)}</span>
          </div>
          <h2 className="mt-1.5 text-base font-semibold text-slate-900">{a.title}</h2>
          {a.resource_id ? (
            <button className="text-sm font-medium text-sky-700 hover:underline" onClick={() => drawer.open(a.resource_id!)}>
              {a.name}
            </button>
          ) : (
            <span className="text-sm text-slate-500">Team-level</span>
          )}
          <p className="mt-2 text-sm leading-relaxed text-slate-700" data-testid="alert-why">{a.why}</p>
          <dl className="mt-3 grid grid-cols-3 gap-2 text-xs">
            <div>
              <dt className="label">Evidence</dt>
              <dd className="num text-slate-800">
                {titleCase(a.evidence.metric)}: {String(a.evidence.value)}
              </dd>
            </div>
            <div>
              <dt className="label">Rule</dt>
              <dd className="num text-slate-800">{String(a.evidence.threshold)}</dd>
            </div>
            <div>
              <dt className="label">First seen</dt>
              <dd className="text-slate-800">
                {formatDateTimeIST(a.first_seen)}
                {a.occurrences > 1 && ` · ×${a.occurrences}`}
              </dd>
            </div>
          </dl>
          <p className="mt-3 flex items-start gap-1.5 text-sm text-slate-700">
            <Lightbulb size={14} className="mt-0.5 shrink-0 text-review-600" /> {a.suggested_action}
          </p>
        </div>
        <div className="min-w-0">
          {hasMetrics && metrics.data ? (
            <TimeSeriesChart series={metrics.data} label={chart.label} unit={chart.unit} color={chart.color} bands={band} height={180} testId="alert-chart" yMax={chart.unit ? undefined : 100} />
          ) : (
            <div className="flex h-full items-center justify-center rounded-lg bg-slate-50 text-xs text-slate-400">{hasMetrics ? 'Loading chart…' : 'No chart for this alert'}</div>
          )}
        </div>
      </div>
    </article>
  )
}
