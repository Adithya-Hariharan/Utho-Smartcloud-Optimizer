import clsx from 'clsx'
import { FlaskConical } from 'lucide-react'
import { Page } from '../components/layout/AppShell'
import { ErrorNote, Loading, Stat } from '../components/common/ui'
import { useAssumptions, useScorecard } from '../api/data'
import { useUi } from '../store/ui'
import { formatINR, formatPct, titleCase } from '../lib/format'

const LIMITATIONS = [
  'Single-thread bottlenecks are hidden by aggregate CPU %.',
  'CPU is assumed to scale linearly with vCPU count; headroom, the one-step prod rule and easy rollback cover the error.',
  'Yearly seasonality is invisible in 30 days; the seasonal_peak tag covers it.',
  'No reserved commitments, egress charges or GST; prices are illustrative.',
  'Resizing usually needs a reboot, so prod changes say "apply in a maintenance window".',
]

export default function Assumptions() {
  const a = useAssumptions()
  const preset = useUi((s) => s.preset)
  const scorecard = useScorecard()
  const sc = scorecard.data

  if (a.isLoading || scorecard.isLoading) return <Page title="Assumptions"><Loading /></Page>
  if (!a.data || !sc) return <Page title="Assumptions"><ErrorNote error={a.error ?? scorecard.error} /></Page>

  return (
    <Page title="Assumptions" subtitle="Every price, threshold and switch the engine uses, with the reason. Change them in config, not in code.">
      <section className="mb-6" aria-labelledby="scorecard">
        <h2 id="scorecard" className="mb-2 text-base font-semibold text-slate-900">Engine scorecard</h2>
        {sc.mock_engine && (
          <p className="mb-3 flex items-start gap-2 rounded-lg border border-review-600/30 bg-review-50 px-3 py-2 text-xs text-review-700" data-testid="scorecard-mock-note">
            <FlaskConical size={14} className="mt-0.5 shrink-0" />
            The backend reports a mock engine: its verdicts come from the truth labels, so this score is not yet a measure of the real engine.
          </p>
        )}
        <div className="mb-3 grid grid-cols-4 gap-3">
          <Stat label="Verdict + reason match" value={`${sc.correct}/${sc.total}`} sub={`${formatPct(sc.accuracy * 100)} · Default preset`} how="Resources whose engine verdict AND reason code both equal the label in truth.csv (GET /api/scorecard)." testId="sc-accuracy" />
          <Stat label="Unsafe downsizes" value={sc.unsafe_downsizes} sub="resizes failing replay or shrinking a must-keep" how="Resize recommendations whose Peak Replay did not pass, plus recommendations on resources the truth says must be kept, rejected, flagged or excluded. Must be 0." tone={sc.unsafe_downsizes ? 'danger' : 'save'} testId="sc-unsafe" />
          <Stat label="Clean-up recall" value={`${sc.cleanup_recall.found}/${sc.cleanup_recall.expected}`} sub="idle, orphans, unused IPs, stopped VMs" how="Of the resources labelled IDLE, ORPHAN_VOLUME, UNUSED_IP or STOPPED_VM in truth.csv, how many the engine recommends acting on." testId="sc-cleanup" />
          <Stat label="Mismatches" value={sc.mismatches.length} sub="see below" how="Resources where verdict or reason code differs from truth.csv; listed in the table below." testId="sc-mismatch" />
        </div>
        <div className="grid grid-cols-2 gap-4">
          <div className="card overflow-hidden">
            <table className="w-full text-sm" data-testid="sc-verdicts">
              <thead className="bg-slate-50">
                <tr>
                  <th className="th">Verdict</th>
                  <th className="th text-right">Expected</th>
                  <th className="th text-right">Predicted</th>
                  <th className="th text-right">Precision</th>
                  <th className="th text-right">Recall</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {sc.by_verdict.map((v) => (
                  <tr key={v.verdict}>
                    <td className="td font-medium capitalize">{v.verdict}</td>
                    <td className="td num text-right">{v.expected}</td>
                    <td className="td num text-right">{v.predicted}</td>
                    <td className="td num text-right">{formatPct(v.precision * 100, 0)}</td>
                    <td className="td num text-right">{formatPct(v.recall * 100, 0)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="card overflow-hidden">
            <table className="w-full text-sm">
              <thead className="bg-slate-50">
                <tr>
                  <th className="th">Archetype</th>
                  <th className="th text-right">Resources</th>
                  <th className="th text-right">Correct</th>
                  <th className="th text-right">Precision</th>
                  <th className="th text-right">Recall</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {sc.by_archetype.map((x) => (
                  <tr key={x.archetype}>
                    <td className="td">{titleCase(x.archetype)}</td>
                    <td className="td num text-right">{x.total}</td>
                    <td className={clsx('td num text-right', x.correct < x.total && 'font-semibold text-danger-700')}>{x.correct}</td>
                    <td className="td num text-right">{formatPct(x.precision * 100, 0)}</td>
                    <td className="td num text-right">{formatPct(x.recall * 100, 0)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
        {sc.mismatches.length > 0 && (
          <div className="card mt-3 overflow-hidden" data-testid="sc-mismatches">
            <table className="w-full text-sm">
              <thead className="bg-slate-50">
                <tr>
                  <th className="th">Resource</th>
                  <th className="th">Expected</th>
                  <th className="th">Got</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {sc.mismatches.map((m) => (
                  <tr key={m.name}>
                    <td className="td font-medium">{m.name}</td>
                    <td className="td font-mono text-xs">{m.expected}</td>
                    <td className="td font-mono text-xs text-danger-700">{m.got}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <div className="grid grid-cols-2 gap-4">
        <section className="card overflow-hidden">
          <h2 className="border-b border-slate-100 px-4 py-3 text-sm font-semibold text-slate-800">Prices (illustrative, ex-GST, all regions equal)</h2>
          <table className="w-full text-sm" data-testid="pricing-table">
            <thead className="bg-slate-50">
              <tr>
                <th className="th">Item</th>
                <th className="th text-right">vCPU</th>
                <th className="th text-right">RAM</th>
                <th className="th text-right">Price</th>
                <th className="th">Basis</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {a.data.pricing.map((p) => (
                <tr key={p.item}>
                  <td className="td font-medium">{p.item.replace('_', ' ')}</td>
                  <td className="td num text-right">{p.vcpu ?? '—'}</td>
                  <td className="td num text-right">{p.ram_gb ? `${p.ram_gb} GB` : '—'}</td>
                  <td className="td num text-right">
                    {formatINR(p.monthly_inr)} <span className="text-2xs text-slate-500">{p.unit.replace('per ', '/ ')}</span>
                  </td>
                  <td className="td text-xs text-slate-500">{p.basis}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>

        <section className="card overflow-hidden">
          <h2 className="border-b border-slate-100 px-4 py-3 text-sm font-semibold text-slate-800">Presets</h2>
          <table className="w-full text-sm" data-testid="presets-table">
            <thead className="bg-slate-50">
              <tr>
                <th className="th">Preset</th>
                <th className="th">Percentile</th>
                <th className="th">CPU target</th>
                <th className="th">Replay limit</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {a.data.presets.map((p) => (
                <tr key={p.id} className={clsx(p.id === preset && 'bg-sky-50')} aria-current={p.id === preset}>
                  <td className="td font-medium">{p.label}{p.id === preset && <span className="ml-1.5 text-2xs text-sky-700">active</span>}</td>
                  <td className="td text-xs">{p.percentile}</td>
                  <td className="td text-xs">{p.cpu_target}</td>
                  <td className="td text-xs">{p.replay_limit}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <h2 className="border-y border-slate-100 px-4 py-3 text-sm font-semibold text-slate-800">Switches</h2>
          <table className="w-full text-sm">
            <tbody className="divide-y divide-slate-100">
              {a.data.switches.map((s) => (
                <tr key={s.name}>
                  <td className="td font-mono text-xs">{s.name}</td>
                  <td className="td num text-xs font-semibold">{String(s.value)}</td>
                  <td className="td text-xs text-slate-500">{s.why}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>

        <section className="card col-span-2 overflow-hidden">
          <h2 className="border-b border-slate-100 px-4 py-3 text-sm font-semibold text-slate-800">Thresholds</h2>
          <table className="w-full text-sm" data-testid="thresholds-table">
            <tbody className="divide-y divide-slate-100">
              {a.data.thresholds.map((t) => (
                <tr key={t.name}>
                  <td className="td w-56 font-medium">{t.name}</td>
                  <td className="td w-72 num text-slate-800">{t.value}</td>
                  <td className="td text-xs text-slate-500">{t.why}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>

        <section className="card card-pad col-span-2">
          <h2 className="mb-2 text-sm font-semibold text-slate-800">Known limitations</h2>
          <ul className="list-inside list-disc space-y-1 text-sm text-slate-600">
            {LIMITATIONS.map((l) => <li key={l}>{l}</li>)}
          </ul>
        </section>
      </div>
    </Page>
  )
}
