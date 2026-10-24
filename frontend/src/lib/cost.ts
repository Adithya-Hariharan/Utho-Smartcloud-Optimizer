// Cost math for accept/reject. Rules (PLAN §9):
//  * Each resource contributes exactly once: after = Σ options[key(accepted)].monthly_inr_after.
//  * Overlapping actions are never added: resize+schedule uses its own combined option.
//  * Rupees are integers from the server; the browser only sums them.
//  * Upsizes are a separate "risk fixes" line, never netted silently into savings.
import type { ActionType, Recommendation } from '../types/contract'

export const ACTION_ORDER: Record<ActionType, number> = {
  snapshot: 1, delete: 2, release: 2, stop: 2, resize: 3, shrink_volume: 3, upsize: 3, schedule: 4,
}
const RANK: ActionType[] = ['snapshot', 'delete', 'release', 'stop', 'resize', 'shrink_volume', 'upsize', 'schedule']

/** Accepted action types → option key in apply order ("resize+schedule"); nothing → "none". */
export function optionKey(actions: readonly ActionType[]): string {
  if (!actions.length) return 'none'
  return [...new Set(actions)]
    .sort((a, b) => ACTION_ORDER[a] - ACTION_ORDER[b] || RANK.indexOf(a) - RANK.indexOf(b))
    .join('+')
}

export function actionsOf(key: string): ActionType[] {
  return key === 'none' ? [] : (key.split('+') as ActionType[])
}

export interface Decision {
  resourceId: string
  status: 'accepted' | 'rejected'
  /** the option the user accepted, e.g. "resize" or "resize+schedule" */
  optionKey: string
  /** target plan at the time of accepting, used to detect preset changes (F8) */
  targetPlan: string | null
}
export type Decisions = Record<string, Decision>

export const isActionable = (r: Recommendation) => r.verdict === 'recommend' || r.verdict === 'upsize'

/** The option key that currently applies to a resource. */
export function appliedKey(r: Recommendation, d: Decision | undefined): string {
  if (!d || d.status !== 'accepted') return 'none'
  return d.optionKey in r.options ? d.optionKey : 'none'
}

export const envKey = (env: string | null | undefined) => env || 'untagged'

export interface Totals {
  before: number
  after: number
  /** Σ positive savings from accepted non-upsize changes */
  saving: number
  /** Σ extra cost of accepted upsizes (shown as its own line) */
  riskFixes: number
  savingPct: number
  accepted: number
  rejected: number
  byEnv: Record<string, { before: number; after: number }>
}

export function totals(items: readonly Recommendation[], decisions: Decisions): Totals {
  const t: Totals = { before: 0, after: 0, saving: 0, riskFixes: 0, savingPct: 0, accepted: 0, rejected: 0, byEnv: {} }
  const seen = new Set<string>()
  for (const r of items) {
    const id = r.resource.resource_id
    if (seen.has(id)) continue // one resource, one contribution, whatever the input
    seen.add(id)
    const d = decisions[id]
    const key = appliedKey(r, d)
    const after = r.options[key].monthly_inr_after
    t.before += r.current.monthly_inr
    t.after += after
    const delta = r.current.monthly_inr - after
    if (r.verdict === 'upsize' && delta < 0) t.riskFixes += -delta
    else t.saving += delta
    if (key !== 'none') t.accepted++
    if (d?.status === 'rejected') t.rejected++
    const e = envKey(r.resource.env)
    t.byEnv[e] ??= { before: 0, after: 0 }
    t.byEnv[e].before += r.current.monthly_inr
    t.byEnv[e].after += after
  }
  t.savingPct = t.before ? (t.saving / t.before) * 100 : 0
  return t
}

/** What the default preset would save if every actionable recommendation's default option were accepted. */
export function potential(items: readonly Recommendation[]): { saving: number; pct: number; count: number } {
  let saving = 0, before = 0, count = 0
  for (const r of items) {
    before += r.current.monthly_inr
    if (r.verdict === 'recommend') {
      const s = r.options[r.default_option]?.saving_inr ?? 0
      if (s > 0) { saving += s; count++ }
    }
  }
  return { saving, pct: before ? (saving / before) * 100 : 0, count }
}

export interface ReconcileResult {
  decisions: Decisions
  reset: { resourceId: string; name: string; why: string }[]
}

/**
 * F8: after a preset change, keep a decision only if the same option still exists with the
 * same target plan. Anything else is dropped and reported so the UI can say so.
 */
export function reconcile(decisions: Decisions, items: readonly Recommendation[]): ReconcileResult {
  const byId = new Map(items.map((r) => [r.resource.resource_id, r]))
  const out: Decisions = {}
  const reset: ReconcileResult['reset'] = []
  for (const d of Object.values(decisions)) {
    const r = byId.get(d.resourceId)
    if (!r) continue
    if (d.status === 'rejected') { out[d.resourceId] = d; continue }
    const target = r.target?.plan ?? null
    if (!isActionable(r)) reset.push({ resourceId: d.resourceId, name: r.resource.name, why: `now ${r.verdict}` })
    else if (!(d.optionKey in r.options)) reset.push({ resourceId: d.resourceId, name: r.resource.name, why: `option ${d.optionKey} no longer offered` })
    else if (target !== d.targetPlan) reset.push({ resourceId: d.resourceId, name: r.resource.name, why: `target changed ${d.targetPlan ?? '—'} → ${target ?? '—'}` })
    else out[d.resourceId] = d
  }
  return { decisions: out, reset }
}
