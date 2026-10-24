// Client-side export of accepted decisions: CSV for finance, Markdown for the ticket,
// and a dry-run shell script for the engineer. Every figure comes from the option the user accepted.
import type { RecEnvelope, Recommendation } from '../types/contract'
import { actionsOf, appliedKey, totals, type Decisions } from './cost'
import { formatINR } from './format'
import { optionLabel } from './labels'

export interface Accepted { r: Recommendation; key: string }

export function accepted(env: RecEnvelope, decisions: Decisions): Accepted[] {
  return env.items
    .map((r) => ({ r, key: appliedKey(r, decisions[r.resource.resource_id]) }))
    .filter((x) => x.key !== 'none')
    .sort((a, b) => b.r.options[b.key].saving_inr - a.r.options[a.key].saving_inr)
}

const csvCell = (v: string | number) => {
  const s = String(v)
  return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s
}

export function toCsv(env: RecEnvelope, decisions: Decisions): string {
  const head = ['resource_id', 'name', 'env', 'team', 'region', 'action', 'current_plan', 'target_plan', 'monthly_before_inr', 'monthly_after_inr', 'saving_inr', 'risk', 'formula']
  const rows = accepted(env, decisions).map(({ r, key }) => [
    r.resource.resource_id, r.resource.name, r.resource.env ?? 'untagged', r.resource.team ?? 'unowned', r.resource.region ?? '', key,
    r.current.plan ?? '', r.target?.plan ?? '', r.current.monthly_inr, r.options[key].monthly_inr_after, r.options[key].saving_inr, r.risk?.level ?? '', r.options[key].formula,
  ])
  return [head, ...rows].map((row) => row.map(csvCell).join(',')).join('\n') + '\n'
}

export function toMarkdown(env: RecEnvelope, decisions: Decisions, presetLabel: string): string {
  const t = totals(env.items, decisions)
  const list = accepted(env, decisions)
  const lines = [
    `# SmartCloud Optimizer: accepted changes`,
    '',
    `Preset **${presetLabel}** · data window ${env.data_window.start.slice(0, 10)} to ${env.data_window.end.slice(0, 10)} (IST)${env.mock_engine ? ' · **mock engine**' : ''}`,
    '',
    `| | Monthly |`,
    `|---|---:|`,
    `| Before | ${formatINR(t.before)} |`,
    `| After | ${formatINR(t.after)} |`,
    `| Saving | ${formatINR(t.saving)} (${t.savingPct.toFixed(1)}%) |`,
    ...(t.riskFixes ? [`| Risk fixes (upsizes) | +${formatINR(t.riskFixes)} |`] : []),
    '',
    `| Resource | Env | Action | Saving / mo | Risk | Formula |`,
    `|---|---|---|---:|---|---|`,
    ...list.map(({ r, key }) => `| ${r.resource.name} | ${r.resource.env ?? 'untagged'} | ${optionLabel(key, r)} | ${formatINR(r.options[key].saving_inr)} | ${r.risk?.level ?? '—'} | ${r.options[key].formula.replace(/\|/g, '/')} |`),
    '',
  ]
  return lines.join('\n')
}

/** Dry-run by default. `cloudctl` is a placeholder for the provider CLI. */
export function toScript(env: RecEnvelope, decisions: Decisions): string {
  const list = accepted(env, decisions)
  const out = [
    '#!/usr/bin/env bash',
    '# SmartCloud Optimizer: apply accepted changes.',
    '# DRY RUN by default; set DRY_RUN=0 to execute. `cloudctl` is a placeholder for your provider CLI.',
    '# Prod changes: apply in a maintenance window. Snapshots are always taken before delete.',
    'set -euo pipefail',
    'DRY_RUN="${DRY_RUN:-1}"',
    'run() { if [ "$DRY_RUN" = "1" ]; then echo "[dry-run] $*"; else "$@"; fi; }',
    '',
  ]
  list.forEach(({ r, key }, n) => {
    const id = r.resource.resource_id
    out.push(`# ${n + 1}. ${r.resource.name} (${id}): ${optionLabel(key, r)} · saves ${formatINR(r.options[key].saving_inr)}/mo · risk ${r.risk?.level ?? '—'}`)
    for (const a of actionsOf(key)) {
      if (a === 'snapshot') out.push(`run cloudctl snapshot create --resource ${id} --name pre-optimizer-${id}`)
      if (a === 'stop') out.push(`run cloudctl vm stop --id ${id}`, `#   rollback: cloudctl vm start --id ${id}`)
      if (a === 'delete') out.push(`echo "hold 14 days, then: cloudctl ${r.resource.type} delete --id ${id}"`, `#   rollback: restore from snapshot pre-optimizer-${id}`)
      if (a === 'release') out.push(`run cloudctl ip release --id ${id}`)
      if (a === 'resize' || a === 'upsize') out.push(`run cloudctl vm resize --id ${id} --plan ${r.target?.plan}`, `#   rollback: cloudctl vm resize --id ${id} --plan ${r.current.plan}`)
      if (a === 'shrink_volume') out.push(`run cloudctl volume migrate --id ${id} --size-gb 100`, `#   rollback: keep the old volume until verified`)
      if (a === 'schedule')
        for (const w of r.schedule?.windows ?? []) out.push(`run cloudctl schedule add --id ${id} --tz Asia/Kolkata --off "${w.days} ${w.start}" --on "${w.end}"`)
    }
    out.push('')
  })
  return out.join('\n')
}

export function download(filename: string, text: string, type: string) {
  const url = URL.createObjectURL(new Blob([text], { type }))
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
