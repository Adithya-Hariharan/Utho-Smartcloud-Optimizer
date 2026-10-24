import { useMemo } from 'react'
import { useSearchParams } from 'react-router-dom'
import clsx from 'clsx'
import { Page } from '../components/layout/AppShell'
import { ErrorNote, HowTip, Loading, Stat } from '../components/common/ui'
import { useWhatIf } from '../api/data'
import { offMask, offString, type OffPolicy } from '../lib/whatif'
import { formatINR, titleCase } from '../lib/format'
import { useResourceDrawer } from '../lib/useDrawer'

const HOURS = Array.from({ length: 24 }, (_, h) => h)
const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
const hh = (h: number) => `${String(h).padStart(2, '0')}:00`

export default function WhatIf() {
  const drawer = useResourceDrawer()
  const [params, setParams] = useSearchParams()
  const env = params.get('env') ?? 'dev'
  const input: OffPolicy = {
    start: Number(params.get('from') ?? 20),
    end: Number(params.get('to') ?? 8),
    weekends: (params.get('weekends') ?? '1') === '1',
  }
  const set = (k: string, v: string) =>
    setParams((p) => {
      const n = new URLSearchParams(p)
      n.set(k, v)
      return n
    }, { replace: true })

  const whatif = useWhatIf({ env, off: offString(input.start, input.end), weekends: input.weekends })
  const result = whatif.data
  const mask = useMemo(() => offMask(input), [input.start, input.end, input.weekends])

  if (whatif.error && !result) return <Page title="What-if"><ErrorNote error={whatif.error} /></Page>
  if (!result) return <Page title="What-if"><Loading /></Page>

  return (
    <Page title="What-if" subtitle="Try a blanket off-hours policy and see what it saves, and which machines it would break. Times are IST.">
      <div className="mb-4 grid grid-cols-[320px_1fr] gap-4">
        <section className="card card-pad space-y-3" aria-label="Policy">
          <label className="block">
            <span className="label">Environment</span>
            <select className="input mt-1 w-full" value={env} onChange={(e) => set('env', e.target.value)} data-testid="wi-env">
              <option value="dev">Dev</option>
              <option value="staging">Staging</option>
              <option value="nonprod">Dev + staging</option>
            </select>
          </label>
          <div className="grid grid-cols-2 gap-2">
            <label className="block">
              <span className="label">Off from</span>
              <select className="input mt-1 w-full" value={input.start} onChange={(e) => set('from', e.target.value)} data-testid="wi-from">
                {HOURS.map((h) => <option key={h} value={h}>{hh(h)}</option>)}
              </select>
            </label>
            <label className="block">
              <span className="label">Back on at</span>
              <select className="input mt-1 w-full" value={input.end} onChange={(e) => set('to', e.target.value)} data-testid="wi-to">
                {HOURS.map((h) => <option key={h} value={h}>{hh(h)}</option>)}
              </select>
            </label>
          </div>
          <label className="flex items-center gap-2 text-sm text-slate-700">
            <input type="checkbox" checked={input.weekends} onChange={(e) => set('weekends', e.target.checked ? '1' : '0')} data-testid="wi-weekends" className="h-4 w-4 rounded border-slate-300" />
            Off all weekend (Sat–Sun)
          </label>
          <div>
            <div className="label mb-1">The policy, hour by hour</div>
            <div className="grid grid-cols-[28px_repeat(24,1fr)] gap-px text-[9px] text-slate-400" aria-label="Off-hours mask">
              <span />
              {HOURS.map((h) => <span key={h} className="text-center">{h % 6 === 0 ? h : ''}</span>)}
              {DAYS.map((d, di) => (
                <div key={d} className="contents">
                  <span>{d}</span>
                  {HOURS.map((h) => (
                    <span key={h} className={clsx('h-3 rounded-[2px]', mask[di * 24 + h] ? 'bg-slate-700' : 'bg-slate-100')} title={`${d} ${hh(h)}: ${mask[di * 24 + h] ? 'off' : 'on'}`} />
                  ))}
                </div>
              ))}
            </div>
            <p className="mt-1 text-2xs text-slate-500">Dark = off.</p>
          </div>
        </section>

        <div className="space-y-3">
          <div className="grid grid-cols-3 gap-3">
            <Stat label="Off per week" value={`${result.off_hours_per_week} h`} sub={`on ${168 - result.off_hours_per_week} h`} testId="wi-off" />
            <Stat
              label="Saving if applied blindly"
              value={`${formatINR(result.blind_saving_inr)}/mo`}
              sub={<span className={result.disrupted ? 'font-semibold text-danger-700' : ''}>breaks {result.disrupted} VM{result.disrupted === 1 ? '' : 's'}</span>}
              how="Σ compute price × off-hours ÷ 168 over every VM in scope except policy exclusions. Disk keeps billing while stopped."
              testId="wi-blind"
            />
            <Stat
              label="Safe saving"
              value={`${formatINR(result.safe_saving_inr)}/mo`}
              sub="only VMs quiet in every week of the window"
              how="Same formula, counting only VMs whose hourly p95 CPU stayed under 5% in every off hour of every week."
              tone="save"
              testId="wi-safe"
            />
          </div>
          <section className="card overflow-hidden">
            <table className="w-full text-sm" data-testid="wi-table">
              <thead className="border-b border-slate-200 bg-slate-50">
                <tr>
                  <th className="th">VM</th>
                  <th className="th">Status</th>
                  <th className="th">
                    <HowTip how="Off hours in which this VM's hourly p95 CPU reached 5% in at least one week.">Why</HowTip>
                  </th>
                  <th className="th text-right">Saving / mo</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {result.rows.map((r) => (
                  <tr key={r.resource_id} className="cursor-pointer hover:bg-slate-50" onClick={() => drawer.open(r.resource_id)} data-testid={`wi-row-${r.name}`}>
                    <td className="td">
                      <div className="whitespace-nowrap font-medium text-slate-900">{r.name}</div>
                      <div className="whitespace-nowrap text-2xs text-slate-500">{titleCase(r.env)} · {titleCase(r.team)} · {r.plan_id}</div>
                    </td>
                    <td className="td">
                      <span
                        className={clsx(
                          'whitespace-nowrap rounded-full px-2 py-0.5 text-2xs font-semibold ring-1 ring-inset',
                          r.status === 'disrupted' && 'bg-danger-50 text-danger-700 ring-danger-600/25',
                          r.status === 'safe' && 'bg-save-50 text-save-700 ring-save-600/25',
                          r.status === 'excluded' && 'bg-slate-100 text-slate-600 ring-slate-400/30',
                        )}
                        data-testid="wi-status"
                      >
                        {r.status === 'disrupted' ? 'Would break' : r.status === 'safe' ? 'Safe' : 'Excluded'}
                      </span>
                    </td>
                    <td className="td text-xs text-slate-600">{r.note}</td>
                    <td className={clsx('td num text-right', r.status === 'safe' ? 'font-semibold text-save-700' : 'text-slate-400')}>{r.status === 'excluded' ? '—' : formatINR(r.saving_inr)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
        </div>
      </div>
    </Page>
  )
}
