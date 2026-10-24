import type { ActionType, ReasonCode, Recommendation, Verdict } from '../types/contract'
import { actionsOf } from './cost'

export const VERDICT_META: Record<Verdict, { label: string; cls: string; dot: string }> = {
  recommend: { label: 'Save', cls: 'bg-save-50 text-save-700 ring-save-600/25', dot: 'bg-save-600' },
  reject: { label: 'Checked & kept', cls: 'bg-kept-50 text-kept-700 ring-kept-600/25', dot: 'bg-kept-600' },
  flag: { label: 'Review', cls: 'bg-review-50 text-review-700 ring-review-600/25', dot: 'bg-review-600' },
  exclude: { label: 'Excluded', cls: 'bg-slate-100 text-slate-600 ring-slate-400/30', dot: 'bg-slate-400' },
  healthy: { label: 'Healthy', cls: 'bg-healthy-50 text-healthy-700 ring-healthy-600/25', dot: 'bg-healthy-600' },
  upsize: { label: 'Upsize', cls: 'bg-upsize-50 text-upsize-700 ring-upsize-600/25', dot: 'bg-upsize-600' },
}

export const REASON_LABEL: Record<ReasonCode, string> = {
  IDLE: 'Idle',
  UNDERUSED: 'Underused',
  OFF_HOURS: 'Quiet off-hours',
  ORPHAN_VOLUME: 'Orphan volume',
  OVERSIZED_VOLUME: 'Oversized volume',
  UNUSED_IP: 'Unused IP',
  STOPPED_VM: 'Stopped 30+ days',
  VETO_MEMORY: 'Memory-bound',
  VETO_IOPS: 'Disk-bound (IOPS)',
  VETO_NETWORK: 'Network is the workload',
  VETO_GROWTH: 'Growing toward capacity',
  VETO_LEAK: 'Memory leak suspected',
  VETO_RECURRING_PEAK: 'Recurring peak',
  PEAK_REPLAY_FAILED: 'Peak Replay failed',
  NO_CHEAPER_PLAN: 'No cheaper plan fits',
  ONE_OFF_PEAK: 'One-off peak',
  WENT_QUIET: 'Went quiet',
  RESERVED_MEMORY: 'Reserved memory',
  PEAK_UNDER_OBSERVED: 'Peak hours under-observed',
  IDLE_PROD: 'Idle production',
  IDLE_VOLUME_REVIEW: 'Idle volume',
  POLICY_NEVER: 'Policy: never',
  TAG_DR_STANDBY: 'DR standby',
  TAG_AUTOSCALED: 'Autoscaled node',
  TAG_SEASONAL: 'Seasonal peak',
  TAG_ALLOWLISTED_IP: 'Allowlisted IP',
  STATEFUL_PROD: 'Stateful production',
  HISTORY_TOO_SHORT: 'Too new (< 14 days)',
  RECENTLY_RESIZED: 'Recently resized',
  LOW_COVERAGE: 'Low data coverage',
  ACTIVE_ANOMALY: 'Active anomaly',
  NO_TELEMETRY: 'No telemetry',
  UNKNOWN_PRICE: 'Unknown price',
  ORPHAN_TOO_NEW: 'Orphan too new',
  STOPPED_RECENTLY: 'Stopped recently',
  NOT_IN_INVENTORY: 'Not in inventory',
  RIGHT_SIZED: 'Right-sized',
  BELOW_FLOOR: 'Below ₹500 floor',
  UNDER_PROVISIONED: 'Under-provisioned',
}

export const ACTION_LABEL: Record<ActionType, string> = {
  snapshot: 'Snapshot',
  delete: 'delete',
  release: 'Release IP',
  stop: 'Stop',
  resize: 'Resize',
  shrink_volume: 'Shrink volume',
  upsize: 'Upsize',
  schedule: 'Schedule',
}

/** "Resize B4 → B2 + schedule", "Snapshot + delete", "No change" */
export function optionLabel(key: string, r?: Recommendation): string {
  if (key === 'none') return 'No change'
  return actionsOf(key)
    .map((a, i) => {
      let s = ACTION_LABEL[a]
      if ((a === 'resize' || a === 'upsize') && r?.target) s += ` ${r.current.plan} → ${r.target.plan}`
      return i === 0 ? s : s.toLowerCase()
    })
    .join(' + ')
}

export const ENV_ORDER = ['prod', 'staging', 'dev', 'untagged']
export const titleEnv = (e: string | null) => (e ? e[0].toUpperCase() + e.slice(1) : 'Untagged')
