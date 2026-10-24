import { useMemo, useState } from 'react'
import { ChevronDown, ChevronRight, ShieldCheck } from 'lucide-react'
import clsx from 'clsx'
import { Page } from '../components/layout/AppShell'
import { FilterBar, distinct, matches, useUrlFilters } from '../components/common/FilterBar'
import { Empty, ErrorNote, HowTip, Loading, Stat, StatRow, VerdictBadge } from '../components/common/ui'
import { Sparkline } from '../components/charts/Sparkline'
import { SERIES } from '../components/charts/theme'
import { useRecs } from '../api/recs'
import { useResources } from '../api/data'
import { KEPT_GROUPS, keptBecause, keptGroupOf } from '../lib/kept'
import { formatINR, formatPct, titleCase } from '../lib/format'
import { REASON_LABEL, titleEnv } from '../lib/labels'
import { useResourceDrawer } from '../lib/useDrawer'
import type { Recommendation } from '../types/contract'

const PREVIEW = 4

export default function Kept() {
  const recs = useRecs()
  const resources = useResources()
  const filters = useUrlFilters(['env', 'team', 'q'])
  const daily = useMemo(() => Object.fromEntries((resources.data ?? []).map((r) => [r.resource_id, r.daily_max ?? r.daily_p95])), [resources.data])

  const kept = useMemo(() => (recs.data?.items ?? []).filter((r) => keptGroupOf(r)), [recs.data])
  const f = filters.values
  const visible = kept.filter(
    (r) => matches(f.env, r.resource.env) && matches(f.team, r.resource.team) && (!f.q || r.resource.name.toLowerCase().includes(f.q.toLowerCase())),
  )
  const groups = KEPT_GROUPS.map((g) => ({ ...g, items: visible.filter((r) => keptGroupOf(r) === g.id) }))
    .filter((g) => g.items.length)
    .sort((a, b) => b.items.length - a.items.length)

  const naiveCut = kept.reduce((s, r) => s + (r.evidence.naive?.saving_inr ?? 0), 0)
  const looksWasteful = kept.filter((r) => (r.evidence.metrics?.cpu?.mean ?? 100) < 20).length
  const vetoed = kept.filter((r) => r.verdict === 'reject').length

  if (recs.isLoading) return <Page title="Checked & kept"><Loading /></Page>
  if (recs.error || !recs.data) return <Page title="Checked & kept"><ErrorNote error={recs.error} /></Page>

  return (
    <Page title="Checked & kept" subtitle="Everything we deliberately did not shrink, and the signal that stopped us. An average-based tool would have cut most of these.">
      <StatRow className="md:grid-cols-4">
        <Stat label="Checked & kept" value={kept.length} sub="rejected, flagged, excluded, or healthy-but-quiet" testId="kept-count" tone="kept" />
        <Stat
          label="Look wasteful on average"
          value={looksWasteful}
          sub="mean CPU under 20%, yet kept"
          how="Resources in this list whose 30-day mean CPU is below 20%: an average-based tool would downsize or stop them."
          testId="kept-wasteful"
        />
        <Stat label="Vetoed by a signal" value={vetoed} sub="memory, IOPS, network, peaks, replay" testId="kept-vetoed" />
        <Stat
          label="A naive tool would cut"
          value={`${formatINR(naiveCut)}/mo`}
          sub="savings we refused to claim"
          how="Σ of what an average-CPU sizing would have saved on the rejected and flagged resources. Each would have failed Peak Replay or a veto."
          tone="danger"
          testId="kept-naive"
        />
      </StatRow>

      <div className="mb-3">
        <FilterBar
          filters={filters}
          defs={[
            { key: 'env', label: 'Env', options: distinct(kept, (r) => r.resource.env, titleCase) },
            { key: 'team', label: 'Team', options: distinct(kept, (r) => r.resource.team, titleCase) },
          ]}
        />
      </div>

      <div className="space-y-3">
        {groups.map((g) => (
          <KeptGroup key={g.id} id={g.id} title={g.title} blurb={g.blurb} items={g.items} daily={daily} forceOpen={!!f.q} />
        ))}
        {!groups.length && <div className="card"><Empty hint="Clear a filter or the search to see the kept resources.">Nothing matches these filters</Empty></div>}
      </div>
    </Page>
  )
}

function KeptGroup({ id, title, blurb, items, daily, forceOpen }: { id: string; title: string; blurb: string; items: Recommendation[]; daily: Record<string, (number | null)[] | null>; forceOpen: boolean }) {
  const [open, setOpen] = useState(true)
  const [all, setAll] = useState(false)
  const shown = all || forceOpen ? items : items.slice(0, PREVIEW)
  const naive = items.reduce((s, r) => s + (r.evidence.naive?.saving_inr ?? 0), 0)
  return (
    <section className="card overflow-clip" data-testid={`kept-group-${id}`}>
      <button className="flex w-full flex-wrap items-center gap-x-3 gap-y-1 px-4 py-3 text-left transition-colors duration-150 hover:bg-slate-50" onClick={() => setOpen(!open)} aria-expanded={open}>
        {open ? <ChevronDown size={16} className="text-slate-500" aria-hidden /> : <ChevronRight size={16} className="text-slate-500" aria-hidden />}
        <ShieldCheck size={16} className="text-kept-600" />
        <span className="h-sec">{title}</span>
        <span className="num rounded-full bg-kept-50 px-2 text-2xs font-semibold text-kept-700" data-testid="group-count">
          {items.length}
        </span>
        <span className="hidden flex-1 truncate text-xs text-slate-500 lg:block">{blurb}</span>
        {naive > 0 && <span className="num whitespace-nowrap text-xs text-slate-500 sm:ml-auto">naive tool would cut {formatINR(naive)}/mo</span>}
      </button>
      {open && (
        <>
          <table className="tbl tbl-stack table-fixed border-t border-slate-100">
            <colgroup>
              <col className="w-[200px]" />
              <col className="w-[130px]" />
              <col />
              <col className="w-[140px]" />
              <col className="w-[150px]" />
            </colgroup>
            <thead>
              <tr>
                <th className="th">Resource</th>
                <th className="th">
                  <HowTip how="30-day mean CPU: the number an average-based tool looks at.">Looked like</HowTip>
                </th>
                <th className="th">Kept because</th>
                <th className="th">Daily peak, 30 d</th>
                <th className="th text-right">Naive tool would cut</th>
              </tr>
            </thead>
            <tbody>
              {shown.map((r) => (
                <KeptRow key={r.rec_id} r={r} daily={daily[r.resource.resource_id] ?? null} />
              ))}
            </tbody>
          </table>
          {items.length > PREVIEW && !forceOpen && (
            <button className="w-full border-t border-slate-100 py-2.5 text-xs font-medium text-sky-700 transition-colors hover:bg-slate-50" onClick={() => setAll(!all)}>
              {all ? 'Show fewer' : `Show ${items.length - PREVIEW} more`}
            </button>
          )}
        </>
      )}
    </section>
  )
}

function KeptRow({ r, daily }: { r: Recommendation; daily: (number | null)[] | null }) {
  const drawer = useResourceDrawer()
  const mean = r.evidence.metrics?.cpu?.mean
  const naive = r.evidence.naive
  return (
    <tr className="row-link" onClick={() => drawer.open(r.resource.resource_id)} data-testid={`kept-row-${r.resource.name}`}>
      <td className="td" data-m="main">
        <div className="truncate font-medium text-slate-900">{r.resource.name}</div>
        <div className="flex items-center gap-1.5 text-2xs text-slate-500">
          <VerdictBadge verdict={r.verdict} label={REASON_LABEL[r.reason_code]} />
          <span className="truncate">{titleEnv(r.resource.env)}</span>
        </div>
      </td>
      <td className="td" data-m="full">
        {mean !== undefined ? (
          <span className={clsx('num font-semibold', mean < 20 ? 'text-slate-900' : 'text-slate-500')}>
            {formatPct(mean)} <span className="text-2xs font-normal text-slate-500">avg CPU</span>
          </span>
        ) : (
          <span className="text-slate-500">no metrics</span>
        )}
      </td>
      <td className="td" data-m="full">
        <div className="line-clamp-2 text-[13px] leading-snug text-slate-700" data-testid="kept-because">
          {keptBecause(r)}
        </div>
      </td>
      <td className="td" data-m="full">
        {daily ? (
          <div className="flex items-center gap-2">
            <Sparkline values={daily} width={84} label={`${r.resource.name} daily peak`} color={SERIES[6]} threshold={r.resource.type === 'vm' ? 90 : undefined} />
            <span className="num whitespace-nowrap text-2xs text-slate-600">
              max {Math.max(...daily.filter((v): v is number => v !== null)).toFixed(0)}%
            </span>
          </div>
        ) : (
          <span className="text-2xs text-slate-500">—</span>
        )}
      </td>
      <td className="td num text-right" data-m="aside">
        {naive && naive.saving_inr > 0 ? (
          <span className="text-slate-700">
            {formatINR(naive.saving_inr)}
            {naive.replay_minutes_above_90 ? <div className="text-2xs text-danger-700">{naive.replay_minutes_above_90.toLocaleString('en-IN')} min &gt; 90%</div> : null}
          </span>
        ) : (
          <span className="text-slate-500">—</span>
        )}
      </td>
    </tr>
  )
}
