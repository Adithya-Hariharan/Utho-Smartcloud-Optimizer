import clsx from 'clsx'
import { FlaskConical } from 'lucide-react'
import { Page } from '../components/layout/AppShell'
import { Badge, ErrorNote, Loading, Stat, StatRow } from '../components/common/ui'
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
        <h2 id="scorecard" className="h-sec mb-2.5 text-base">Engine scorecard</h2>
        {sc.mock_engine && (
          <p className="mb-3 flex items-start gap-2 rounded-lg border border-review-600/30 bg-review-50 px-3 py-2 text-xs text-review-700" data-testid="scorecard-mock-note">
            <FlaskConical size={14} className="mt-0.5 shrink-0" />
            The backend reports a mock engine: its verdicts come from the truth labels, so this score is not yet a measure of the real engine.
          </p>
        )}
        <StatRow className="md:grid-cols-4">
          <Stat label="Verdict + reason match" value={`${sc.correct}/${sc.total}`} sub={`${formatPct(sc.accuracy * 100)} · Default preset`} how="Resources whose engine verdict AND reason code both equal the label in truth.csv (GET /api/scorecard)." testId="sc-accuracy" />
          <Stat label="Unsafe downsizes" value={sc.unsafe_downsizes} sub="resizes failing replay or shrinking a must-keep" how="Resize recommendations whose Peak Replay did not pass, plus recommendations on resources the truth says must be kept, rejected, flagged or excluded. Must be 0." tone={sc.unsafe_downsizes ? 'danger' : 'save'} testId="sc-unsafe" />
          <Stat label="Clean-up recall" value={`${sc.cleanup_recall.found}/${sc.cleanup_recall.expected}`} sub="idle, orphans, unused IPs, stopped VMs" how="Of the resources labelled IDLE, ORPHAN_VOLUME, UNUSED_IP or STOPPED_VM in truth.csv, how many the engine recommends acting on." testId="sc-cleanup" />
          <Stat label="Mismatches" value={sc.mismatches.length} sub="see below" how="Resources where verdict or reason code differs from truth.csv; listed in the table below." testId="sc-mismatch" />
        </StatRow>
        <div className="grid gap-4 lg:grid-cols-2">
          <div className="card overflow-x-auto">
            <table className="tbl" data-testid="sc-verdicts">
              <thead>
                <tr>
                  <th className="th">Verdict</th>
                  <th className="th text-right">Expected</th>
                  <th className="th text-right">Predicted</th>
                  <th className="th text-right">Precision</th>
                  <th className="th text-right">Recall</th>
                </tr>
              </thead>
              <tbody>
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
          <div className="card overflow-x-auto">
            <table className="tbl">
              <thead>
                <tr>
                  <th className="th">Archetype</th>
                  <th className="th text-right">Resources</th>
                  <th className="th text-right">Correct</th>
                  <th className="th text-right">Precision</th>
                  <th className="th text-right">Recall</th>
                </tr>
              </thead>
              <tbody>
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
          <div className="card mt-3 overflow-x-auto" data-testid="sc-mismatches">
            <table className="tbl">
              <thead>
                <tr>
                  <th className="th">Resource</th>
                  <th className="th">Expected</th>
                  <th className="th">Got</th>
                </tr>
              </thead>
              <tbody>
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

      <div className="grid items-start gap-4 lg:grid-cols-2">
        <section className="card overflow-x-auto">
          <h2 className="border-b border-slate-100 px-4 py-3 text-sm font-semibold text-slate-800">Prices (illustrative, ex-GST, all regions equal)</h2>
          <table className="tbl" data-testid="pricing-table">
            <thead>
              <tr>
                <th className="th">Item</th>
                <th className="th text-right">vCPU</th>
                <th className="th text-right">RAM</th>
                <th className="th text-right">Price</th>
                <th className="th">Basis</th>
              </tr>
            </thead>
            <tbody>
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

        <section className="card overflow-x-auto">
          <h2 className="border-b border-slate-100 px-4 py-3 text-sm font-semibold text-slate-800">Presets</h2>
          <table className="tbl" data-testid="presets-table">
            <thead>
              <tr>
                <th className="th">Preset</th>
                <th className="th">Percentile</th>
                <th className="th">CPU target</th>
                <th className="th">Replay limit</th>
              </tr>
            </thead>
            <tbody>
              {a.data.presets.map((p) => (
                <tr key={p.id} className={clsx(p.id === preset && 'bg-sky-50')} aria-current={p.id === preset}>
                  <td className="td font-medium">{p.label}{p.id === preset && <Badge tone="brand" className="ml-1.5">active</Badge>}</td>
                  <td className="td text-xs">{p.percentile}</td>
                  <td className="td text-xs">{p.cpu_target}</td>
                  <td className="td text-xs">{p.replay_limit}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <h2 className="border-y border-slate-100 px-4 py-3 text-sm font-semibold text-slate-800">Switches</h2>
          <table className="tbl">
            <tbody>
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

        <section className="card overflow-x-auto lg:col-span-2">
          <h2 className="border-b border-slate-100 px-4 py-3 text-sm font-semibold text-slate-800">Thresholds</h2>
          <table className="tbl tbl-stack" data-testid="thresholds-table">
            <tbody>
              {a.data.thresholds.map((t) => (
                <tr key={t.name}>
                  <td className="td font-medium md:w-56" data-m="main">{t.name}</td>
                  <td className="td num text-slate-800 md:w-72" data-m="aside">{t.value}</td>
                  <td className="td text-xs leading-relaxed text-slate-500" data-m="full">{t.why}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>

        <section className="card p-4 lg:col-span-2">
          <h2 className="h-sec mb-2">Known limitations</h2>
          <ul className="max-w-[75ch] list-outside list-disc space-y-1.5 pl-4 text-sm leading-relaxed text-slate-600 marker:text-slate-400">
            {LIMITATIONS.map((l) => <li key={l}>{l}</li>)}
          </ul>
        </section>
      </div>
    </Page>
  )
}
