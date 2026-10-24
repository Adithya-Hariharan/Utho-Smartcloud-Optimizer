import type { ReasonCode, Recommendation } from '../types/contract'

/** Rejections panel groups, in the order a judge should read them. */
export const KEPT_GROUPS: { id: string; title: string; blurb: string; codes: ReasonCode[] | 'peaks' }[] = [
  { id: 'recurring', title: 'Recurring peak', blurb: 'A predictable spike the average hides: nightly batches, morning bursts, weekly jobs.', codes: ['VETO_RECURRING_PEAK'] },
  { id: 'replay', title: 'Peak Replay failed', blurb: 'Every cheaper size spends time above 90% CPU when the last 30 days are replayed on it.', codes: ['PEAK_REPLAY_FAILED'] },
  { id: 'memory', title: 'Memory', blurb: 'Memory-bound, leaking, or needing more RAM than any cheaper plan has. Memory shortfalls crash; CPU shortfalls only slow.', codes: ['VETO_MEMORY', 'VETO_LEAK', 'NO_CHEAPER_PLAN'] },
  { id: 'io', title: 'Disk, network & growth', blurb: 'The bottleneck is not CPU: IOPS, bandwidth or a filling disk.', codes: ['VETO_IOPS', 'VETO_NETWORK', 'VETO_GROWTH'] },
  { id: 'anomaly', title: 'Active anomaly', blurb: 'Behaviour changed in the last days; never size during an incident.', codes: ['ACTIVE_ANOMALY'] },
  { id: 'review', title: 'Needs human review', blurb: 'Patterns a tool should not decide alone. Flagged with the evidence.', codes: ['ONE_OFF_PEAK', 'WENT_QUIET', 'RESERVED_MEMORY', 'PEAK_UNDER_OBSERVED', 'IDLE_PROD', 'IDLE_VOLUME_REVIEW'] },
  { id: 'tags', title: 'Stateful, tagged or policy', blurb: 'Owners said no, or telemetry alone cannot tell (DR standby, autoscaled nodes, allowlisted IPs).', codes: ['STATEFUL_PROD', 'TAG_DR_STANDBY', 'TAG_AUTOSCALED', 'TAG_SEASONAL', 'TAG_ALLOWLISTED_IP', 'POLICY_NEVER'] },
  { id: 'data', title: 'Insufficient data', blurb: 'We never act on what we cannot see: too new, too gappy, no metrics or no price.', codes: ['HISTORY_TOO_SHORT', 'LOW_COVERAGE', 'NO_TELEMETRY', 'RECENTLY_RESIZED', 'STOPPED_RECENTLY', 'ORPHAN_TOO_NEW', 'UNKNOWN_PRICE', 'NOT_IN_INVENTORY'] },
  { id: 'peaks', title: 'Kept: peaks need the size', blurb: 'Healthy machines whose average CPU is under 20%. An average-based tool would shrink them; their peaks say no.', codes: 'peaks' },
]

export const LOOKS_WASTEFUL_MEAN_CPU = 20

export function keptGroupOf(r: Recommendation): string | null {
  if (r.verdict === 'healthy') {
    const mean = r.evidence.metrics?.cpu?.mean
    return r.reason_code === 'RIGHT_SIZED' && r.resource.type === 'vm' && mean !== undefined && mean < LOOKS_WASTEFUL_MEAN_CPU ? 'peaks' : null
  }
  if (!['reject', 'flag', 'exclude'].includes(r.verdict)) return null
  return KEPT_GROUPS.find((g) => g.codes !== 'peaks' && g.codes.includes(r.reason_code))?.id ?? 'data'
}

/** One-line "kept because" with the number that decided it. */
export function keptBecause(r: Recommendation): string {
  if (r.veto) {
    const v = typeof r.veto.value === 'number' ? r.veto.value.toLocaleString('en-IN', { maximumFractionDigits: 1 }) : r.veto.value
    return `${r.veto.metric}: ${v} (rule ${r.veto.comparator} ${r.veto.threshold})`
  }
  if (r.verdict === 'healthy') {
    const c = r.evidence.metrics?.cpu
    return c ? `p99 ${c.p99.toFixed(0)}% vs mean ${c.mean.toFixed(1)}%` : r.reason
  }
  return r.reason
}
