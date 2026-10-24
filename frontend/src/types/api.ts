// Response shapes of the backend endpoints other than /api/recommendations (see contract.ts
// and API_CONTRACT.md). One interface per endpoint.
import type { PresetId, ReplayAttempt } from './contract'

/** GET /api/alerts */
export interface Alert {
  alert_id: string
  type: string
  severity: 'critical' | 'warning' | 'info'
  resource_id: string | null
  name: string
  title: string
  why: string
  evidence: { metric: string; value: number | string | null; threshold: number | string; window: { start: string; end: string } | null }
  window: { start: string; end: string } | null
  first_seen: string
  occurrences: number
  suggested_action: string
}
export interface AlertsResponse { mock_engine: boolean; items: Alert[] }

/** GET /api/summary (PLAN §4.5 Summary). The "after accepted" total is computed in the browser. */
export interface SplitTotals { monthly_before_inr: number; potential_after_inr: number }
export interface GrowthDelta { key: string; first30_inr: number; last30_inr: number; delta_inr: number }
export interface Summary {
  /** run-rate: Σ current monthly cost of every resource; equals Σ current.monthly_inr in /api/recommendations */
  monthly_before_inr: number
  /** if every Default-preset recommendation were accepted */
  potential_after_inr: number
  potential_saving_pct: number
  by_env: Record<string, SplitTotals>
  by_team: Record<string, SplitTotals>
  by_region: Record<string, SplitTotals>
  counts: { vm: number; volume: number; ip: number; verdicts: Record<string, number> }
  /** 180 days of daily billed cost */
  bill_trend_6m: { dates: string[]; total: number[]; by_env: Record<string, number[]>; by_team: Record<string, number[]> }
  /** first 30 billed days → last 30, explained by env, team and new vs existing resources */
  growth_waterfall: {
    first30: { start: string; total_inr: number }
    last30: { end: string; total_inr: number }
    growth_ratio: number
    by_env: GrowthDelta[]
    by_team: GrowthDelta[]
    by_age: GrowthDelta[]
    new_resources: { resource_id: string; name: string; team: string; env: string; type: string; created_at: string; monthly_inr: number }[]
  }
}

/** GET /api/data-quality */
export interface DqRow {
  resource_id: string
  name: string
  type: 'vm' | 'volume'
  in_inventory: boolean
  rows_raw: number
  irregular_ts: number
  out_of_order: number
  duplicates: number
  out_of_range: number
  flatline_slots: number
  expected_slots: number
  coverage: number | null
  peak_window_coverage: number | null
  days_of_data: number | null
  longest_gap_hours: number
  gaps: number
}
export interface DqCheck { id: string; fault: string; where: string; injected: string; detected: string; handling: string; ok: boolean }
export interface DataQuality {
  resources: DqRow[]
  faults: { resource_id: string; name: string; fault: string; detail: string }[]
  fault_counts: Record<string, number>
  not_in_inventory: { resource_id: string; name: string }[]
  no_metrics: { resource_id: string; name: string; state: string }[]
  totals: Record<'rows_raw' | 'duplicates' | 'out_of_range' | 'out_of_order' | 'irregular_ts' | 'flatline_slots' | 'metric_rows', number>
  /** injected (generator fault log) vs detected (cleaning step) */
  checks: DqCheck[]
}

/** GET /api/assumptions: config the engine runs on, plus the data window */
export interface Assumptions {
  data_window: { start: string; end: string; timezone: string }
  billing_window: { start: string; end: string }
  counts: { vm: number; volume: number; ip: number; metric_rows: number }
  pricing: { item: string; kind: string; vcpu: number | null; ram_gb: number | null; bandwidth_mbps: number | null; monthly_inr: number; unit: string; basis: string }[]
  thresholds: { name: string; value: string; why: string }[]
  switches: { name: string; value: string | number | boolean; why: string }[]
  presets: { id: PresetId; label: string; percentile: string; cpu_target: string; replay_limit: string }[]
}

/** GET /api/resources/{id}/replay?preset= : actual vs projected CPU on the target plan */
export interface ReplaySeries {
  resource_id: string
  preset: PresetId
  from_plan: string
  to_plan: string
  from_vcpu: number
  to_vcpu: number
  step_seconds: number
  start: string
  actual_cpu: (number | null)[]
  projected_cpu: (number | null)[]
  limit_minutes_above_90: number
  mem_cap_pct: number
  attempts: ReplayAttempt[]
  passed: boolean
}

/** POST /api/whatif  body {"env":"dev","off":"20:00-08:00","weekends":true} (PLAN §10) */
export interface WhatIfRequest { env: string; off: string; weekends: boolean }
export interface WhatIfRow {
  resource_id: string
  name: string
  env: string
  team: string
  plan_id: string
  status: 'safe' | 'disrupted' | 'excluded'
  saving_inr: number
  busy_off_hours: number
  note: string
}
export interface WhatIfResponse {
  input: WhatIfRequest
  off_hours_per_week: number
  rows: WhatIfRow[]
  safe_saving_inr: number
  blind_saving_inr: number
  disrupted: number
  excluded: number
}

/** GET /api/scorecard : Default-preset verdicts vs the generator's truth labels */
export interface Scorecard {
  preset: PresetId
  mock_engine: boolean
  total: number
  correct: number
  accuracy: number
  by_verdict: { verdict: string; expected: number; predicted: number; correct: number; precision: number; recall: number }[]
  by_archetype: { archetype: string; total: number; correct: number; precision: number; recall: number }[]
  unsafe_downsizes: number
  wrongly_shrunk: string[]
  cleanup_recall: { found: number; expected: number }
  mismatches: { name: string; expected: string; got: string }[]
}

/** POST /api/export  body {"accepted":[...], "format":"csv|md|sh|tf"} (PLAN §10). rec_id carries the preset. */
export type ExportFormat = 'csv' | 'md' | 'sh' | 'tf'
export interface ExportRequest { accepted: { rec_id: string; option_key: string }[]; format: ExportFormat }

/** GET /api/forecast?days=90 : bill forecast + carbon. Carbon is per option, like cost, so the browser sums accepted ones. */
export interface CarbonSaving { kwh_month: number; kg_co2_month: number }
export interface Forecast {
  days: number
  method: string
  monthly_now_inr: number
  history: { dates: string[]; total: number[] }
  forecast: { dates: string[]; baseline: number[]; lower: number[]; upper: number[] }
  carbon: {
    coefficients: { w_per_vcpu_min: number; w_per_vcpu_max: number; w_per_gb_ram: number; pue: number; kg_co2_per_kwh: number; source: string }
    fleet_kwh_month: number
    fleet_kg_co2_month: number
    potential_kwh_month: number
    potential_kg_co2_month: number
    /** rec_id → option key → monthly saving */
    by_option: Record<string, Record<string, CarbonSaving>>
  }
}
