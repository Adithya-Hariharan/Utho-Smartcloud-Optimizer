import { useMemo, useState } from 'react'
import { CheckCheck, Layers, RotateCcw, TriangleAlert } from 'lucide-react'
import clsx from 'clsx'
import { Page } from '../components/layout/AppShell'
import { SummaryBar } from '../components/recs/SummaryBar'
import { DecideControl } from '../components/recs/DecideControl'
import { ExportMenu } from '../components/recs/ExportMenu'
import { FilterBar, distinct, matches, useUrlFilters, type FilterDef } from '../components/common/FilterBar'
import { Badge, Empty, ErrorNote, Loading, RiskChip, Tip } from '../components/common/ui'
import { useRecs } from '../api/recs'
import { useDecisions } from '../store/decisions'
import { actionsOf } from '../lib/cost'
import { formatINR, titleCase } from '../lib/format'
import { ACTION_LABEL, REASON_LABEL, optionLabel, titleEnv } from '../lib/labels'
import { useResourceDrawer } from '../lib/useDrawer'
import type { Recommendation } from '../types/contract'

const RISK_RANK = { Low: 0, Medium: 1, High: 2 } as const
const FILTER_KEYS = ['env', 'team', 'region', 'type', 'action', 'risk', 'q']

export default function Recommendations() {
  const recs = useRecs()
  const filters = useUrlFilters(FILTER_KEYS)
  const [sort, setSort] = useState<'monday' | 'saving' | 'name'>('monday')
  const decisions = useDecisions((s) => s.decisions)
  const acceptMany = useDecisions((s) => s.acceptMany)
  const resetAll = useDecisions((s) => s.resetAll)

  const all = recs.data?.items ?? []
  const actionable = useMemo(() => all.filter((r) => r.verdict === 'recommend'), [all])
  const upsizes = useMemo(() => all.filter((r) => r.verdict === 'upsize'), [all])

  const defs: FilterDef[] = useMemo(
    () => [
      { key: 'env', label: 'Env', options: distinct(actionable, (r) => r.resource.env, titleCase) },
      { key: 'team', label: 'Team', options: distinct(actionable, (r) => r.resource.team, titleCase) },
      { key: 'region', label: 'Region', options: distinct(actionable, (r) => r.resource.region, titleCase) },
      { key: 'type', label: 'Type', options: distinct(actionable, (r) => r.resource.type, (v) => v.toUpperCase()) },
      {
        key: 'action',
        label: 'Action',
        options: [...new Set(actionable.flatMap((r) => actionsOf(r.default_option)))].sort().map((a) => ({ value: a, label: ACTION_LABEL[a] })),
      },
      { key: 'risk', label: 'Risk', options: ['Low', 'Medium', 'High'].map((v) => ({ value: v, label: v })) },
    ],
    [actionable],
  )

  const f = filters.values
  const rows = useMemo(() => {
    const list = actionable.filter(
      (r) =>
        matches(f.env, r.resource.env) &&
        matches(f.team, r.resource.team) &&
        matches(f.region, r.resource.region) &&
        matches(f.type, r.resource.type) &&
        (!f.action || actionsOf(r.default_option).includes(f.action as never)) &&
        (!f.risk || r.risk?.level === f.risk) &&
        (!f.q || r.resource.name.toLowerCase().includes(f.q.toLowerCase())),
    )
    const saving = (r: Recommendation) => r.options[r.default_option].saving_inr
    list.sort((a, b) =>
      sort === 'name'
        ? a.resource.name.localeCompare(b.resource.name)
        : sort === 'saving'
          ? saving(b) - saving(a)
          : RISK_RANK[a.risk?.level ?? 'High'] - RISK_RANK[b.risk?.level ?? 'High'] || saving(b) - saving(a),
    )
    return list
  }, [actionable, f, sort])

  // Service groups collapse into one group row, sized on the busiest member (A23).
  const blocks = useMemo(() => {
    const out: ({ kind: 'single'; r: Recommendation } | { kind: 'group'; name: string; members: Recommendation[] })[] = []
    const seen = new Set<string>()
    for (const r of rows) {
      const g = r.resource.service_group
      if (g && r.resource.members.length > 1) {
        if (seen.has(g)) continue
        seen.add(g)
        out.push({ kind: 'group', name: g, members: rows.filter((x) => x.resource.service_group === g) })
      } else out.push({ kind: 'single', r })
    }
    return out
  }, [rows])

  const lowRiskPending = rows.filter((r) => r.risk?.level === 'Low' && !decisions[r.resource.resource_id])

  if (recs.isLoading) return <Page title="Recommendations"><Loading /></Page>
  if (recs.error || !recs.data) return <Page title="Recommendations"><ErrorNote error={recs.error} /></Page>

  return (
    <Page
      title="Recommendations"
      subtitle={`${actionable.length} changes that pass every safety check · sorted low risk, high saving first`}
    >
      <SummaryBar env={recs.data} />
      <div className="mb-3">
        <FilterBar
          defs={defs}
          filters={filters}
          right={
            <>
              <select className="input input-sm" value={sort} onChange={(e) => setSort(e.target.value as typeof sort)} aria-label="Sort">
                <option value="monday">Sort: low risk, high saving</option>
                <option value="saving">Sort: saving</option>
                <option value="name">Sort: name</option>
              </select>
              <button className="btn-outline btn-sm" disabled={!lowRiskPending.length} onClick={() => acceptMany(lowRiskPending)} data-testid="accept-low-risk">
                <CheckCheck size={14} /> Accept {lowRiskPending.length} low-risk
              </button>
              <ExportMenu env={recs.data!} />
              <button className="btn-ghost btn-sm" onClick={resetAll} disabled={!Object.keys(decisions).length} data-testid="reset-decisions">
                <RotateCcw size={14} /> Reset
              </button>
            </>
          }
        />
      </div>

      <div className="card overflow-clip">
        <table className="tbl tbl-stack-xl table-fixed" data-testid="recs-table">
          <RecCols />
          <thead>
            <tr>
              <th className="th sticky top-[var(--summary-h,0px)] z-10 bg-slate-50">Resource</th>
              <th className="th sticky top-[var(--summary-h,0px)] z-10 bg-slate-50">Action</th>
              <th className="th sticky top-[var(--summary-h,0px)] z-10 bg-slate-50">Why</th>
              <th className="th sticky top-[var(--summary-h,0px)] z-10 whitespace-nowrap bg-slate-50 text-right">Saving / mo</th>
              <th className="th sticky top-[var(--summary-h,0px)] z-10 bg-slate-50">Risk</th>
              <th className="th sticky top-[var(--summary-h,0px)] z-10 bg-slate-50 text-right">Decision</th>
            </tr>
          </thead>
          <tbody>
            {blocks.map((b) =>
              b.kind === 'single' ? (
                <RecRow key={b.r.rec_id} r={b.r} />
              ) : (
                <GroupRows key={b.name} name={b.name} members={b.members} />
              ),
            )}
          </tbody>
        </table>
        {!rows.length && (
          <Empty hint={filters.active ? 'Clear a filter to see more.' : 'Nothing passed every safety check for this preset.'}>
            {filters.active ? 'No recommendations match these filters' : 'No recommendations yet'}
          </Empty>
        )}
      </div>

      {upsizes.length > 0 && (
        <section className="mt-8" data-testid="risk-fixes" aria-labelledby="risk-fixes-h">
          <h2 id="risk-fixes-h" className="h-sec mb-1 flex items-center gap-2">
            <TriangleAlert size={15} className="text-upsize-600" aria-hidden /> Risk fixes: these cost money
          </h2>
          <p className="h-sub mb-2.5">Under-provisioned resources that need a bigger plan. They add cost and are never netted against savings.</p>
          <div className="card overflow-clip">
            <table className="tbl tbl-stack-xl table-fixed">
              <RecCols />
              <tbody>
                {upsizes.map((r) => (
                  <RecRow key={r.rec_id} r={r} />
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </Page>
  )
}

function RecCols() {
  return (
    <colgroup>
      <col className="w-[180px]" />
      <col className="w-[200px]" />
      <col />
      <col className="w-[104px]" />
      <col className="w-[96px]" />
      <col className="w-[236px]" />
    </colgroup>
  )
}

function ResourceCell({ r }: { r: Recommendation }) {
  return (
    <div>
      <div className="truncate font-medium text-slate-900" title={r.resource.name}>{r.resource.name}</div>
      <div className="truncate text-2xs text-slate-500">
        {titleEnv(r.resource.env)} · {titleCase(r.resource.team ?? 'unowned')} · {titleCase(r.resource.region)}
        {r.flags.length > 0 && (
          <Tip content={r.flags.map((x) => <div key={x.code}>{x.message}</div>)}>
            <Badge tone="review" className="ml-1.5 py-0">{r.flags.length} flag{r.flags.length > 1 ? 's' : ''}</Badge>
          </Tip>
        )}
      </div>
    </div>
  )
}

function RecRow({ r, indent = false }: { r: Recommendation; indent?: boolean }) {
  const drawer = useResourceDrawer()
  const decision = useDecisions((s) => s.decisions[r.resource.resource_id])
  const opt = r.options[decision?.status === 'accepted' ? decision.optionKey : r.default_option] ?? r.options[r.default_option]
  const saving = opt.saving_inr
  return (
    <tr
      className={clsx(
        'row-link',
        decision?.status === 'accepted' && 'bg-save-50/60 hover:bg-save-50',
        decision?.status === 'rejected' && 'opacity-60 hover:opacity-100',
      )}
      onClick={() => drawer.open(r.resource.resource_id)}
      data-testid={`rec-row-${r.resource.name}`}
    >
      <td className={clsx('td', indent && 'pl-8')} data-m="main">
        <ResourceCell r={r} />
      </td>
      <td className="td" data-m="full">
        <div className="truncate font-medium text-slate-800">{optionLabel(r.default_option, r)}</div>
        <div className="text-2xs text-slate-500">{REASON_LABEL[r.reason_code]}</div>
      </td>
      <td className="td" data-m="full">
        <div className="line-clamp-2 text-[13px] leading-snug text-slate-600">{r.reason}</div>
      </td>
      <td className="td text-right" data-m="aside">
        <Tip content={<span className="font-mono">{opt.formula}</span>}>
          <span className={clsx('num cursor-help text-[15px] font-semibold', saving >= 0 ? 'text-save-700' : 'text-upsize-700')} data-testid="row-saving">
            {formatINR(saving)}
          </span>
        </Tip>
      </td>
      <td className="td">
        <RiskChip risk={r.risk} />
      </td>
      <td className="td" data-m="end">
        <DecideControl r={r} compact={indent} />
      </td>
    </tr>
  )
}

function GroupRows({ name, members }: { name: string; members: Recommendation[] }) {
  const acceptMany = useDecisions((s) => s.acceptMany)
  const decisions = useDecisions((s) => s.decisions)
  const total = members.reduce((s, r) => s + r.options[r.default_option].saving_inr, 0)
  const pending = members.filter((r) => !decisions[r.resource.resource_id])
  const sizedOn = members[0].trace.find((t) => t.step === 'sizing')?.value.match(/sized on ([\w-]+)/)?.[1]
  return (
    <>
      <tr className="bg-slate-50" data-testid={`group-row-${name}`}>
        <td className="td" colSpan={3} data-m="main">
          <div className="flex flex-wrap items-center gap-x-2 font-medium text-slate-900">
            <Layers size={14} className="shrink-0 text-slate-500" aria-hidden /> Service group <span className="font-mono text-xs">{name}</span>
            <span className="text-2xs font-normal text-slate-500">
              {members.length} VMs · one target for all{sizedOn ? `, sized on the busiest member (${sizedOn})` : ''}
            </span>
          </div>
        </td>
        <td className="td num text-right font-semibold text-save-700" data-m="aside">{formatINR(total)}</td>
        <td className="td" data-m="hide" />
        <td className="td text-right" data-m="full">
          <button className="btn-outline btn-sm" disabled={!pending.length} onClick={() => acceptMany(pending)}>
            <CheckCheck size={13} /> Accept group
          </button>
        </td>
      </tr>
      {members.map((r) => (
        <RecRow key={r.rec_id} r={r} indent />
      ))}
    </>
  )
}
