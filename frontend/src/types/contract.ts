// Recommendation contract v1.0 (PLAN.md §4.5) plus the static data files the UI reads.
// When the backend publishes its JSON Schema, regenerate this file from it.

export type Verdict = 'recommend' | 'reject' | 'flag' | 'exclude' | 'healthy' | 'upsize'
export type ResourceType = 'vm' | 'volume' | 'ip'
export type ActionType =
  | 'snapshot' | 'delete' | 'release' | 'stop' | 'resize' | 'shrink_volume' | 'upsize' | 'schedule'
export type PresetId = 'max_savings' | 'balanced' | 'default' | 'max_performance'

export type ReasonCode =
  // recommend
  | 'IDLE' | 'UNDERUSED' | 'OFF_HOURS' | 'ORPHAN_VOLUME' | 'OVERSIZED_VOLUME' | 'UNUSED_IP' | 'STOPPED_VM'
  // reject
  | 'VETO_MEMORY' | 'VETO_IOPS' | 'VETO_NETWORK' | 'VETO_GROWTH' | 'VETO_LEAK' | 'VETO_RECURRING_PEAK'
  | 'PEAK_REPLAY_FAILED' | 'NO_CHEAPER_PLAN'
  // flag
  | 'ONE_OFF_PEAK' | 'WENT_QUIET' | 'RESERVED_MEMORY' | 'PEAK_UNDER_OBSERVED' | 'IDLE_PROD' | 'IDLE_VOLUME_REVIEW'
  // exclude
  | 'POLICY_NEVER' | 'TAG_DR_STANDBY' | 'TAG_AUTOSCALED' | 'TAG_SEASONAL' | 'TAG_ALLOWLISTED_IP' | 'STATEFUL_PROD'
  | 'HISTORY_TOO_SHORT' | 'RECENTLY_RESIZED' | 'LOW_COVERAGE' | 'ACTIVE_ANOMALY' | 'NO_TELEMETRY' | 'UNKNOWN_PRICE'
  | 'ORPHAN_TOO_NEW' | 'STOPPED_RECENTLY' | 'NOT_IN_INVENTORY'
  // healthy / upsize
  | 'RIGHT_SIZED' | 'BELOW_FLOOR' | 'UNDER_PROVISIONED'

export interface ResourceRef {
  resource_id: string
  name: string
  type: ResourceType
  env: string | null
  team: string | null
  owner: string
  region: string | null
  purpose: string | null
  service_group: string | null
  members: string[]
  tags: string[]
  state: string | null
  plan_id: string | null
}

export interface CostBlock {
  plan: string | null
  vcpu: number | null
  ram_gb: number | null
  disk_gb: number | null
  compute_inr: number
  storage_inr: number
  ip_inr: number
  monthly_inr: number
}

export interface Action {
  type: ActionType
  order: number
  description: string
  requires: ActionType[]
  reversible: boolean
  rollback: string
}

export interface Option {
  monthly_inr_after: number
  saving_inr: number
  formula: string
}

export interface ScheduleWindow { days: string; start: string; end: string }
export interface Schedule {
  timezone: string
  off_hours_per_week: number
  on_hours_per_week: number
  windows: ScheduleWindow[]
  busy_hours_excluded: string[]
}

export interface MetricStats { mean: number; p50: number; p95: number; p99: number; max: number }

export interface Evidence {
  window_days: number
  days_of_data: number
  coverage: number
  peak_window_coverage: number | null
  percentile_used: string
  metrics: {
    cpu: MetricStats | null
    mem: MetricStats | null
    iops_pct: MetricStats | null
    net_pct: MetricStats | null
    disk_used: MetricStats | null
  } | null
  recurring_peak: { window_ist: string; days: number } | null
  naive: { action: string; target_plan: string | null; saving_inr: number; basis: string; replay_minutes_above_90: number | null } | null
}

export interface ReplayAttempt { plan: string; minutes_above_90: number; max_cpu_pct: number; max_mem_pct: number; passed: boolean }
export interface Replay {
  limit_minutes_above_90: number
  mem_cap_pct: number
  attempts: ReplayAttempt[]
  passed: boolean
  chosen_plan: string | null
  from_vcpu: number
  from_ram_gb: number
}

export interface Veto {
  signal: string
  metric: string
  value: number
  threshold: number
  comparator: string
  message: string
}

export interface Risk {
  level: 'Low' | 'Medium' | 'High'
  score: number
  points: { factor: string; points: number; detail: string }[]
  confidence: 'High' | 'Medium' | 'Low'
  confidence_basis: string
}

export interface TraceStep {
  step: string
  check: string
  value: string
  threshold: string
  result: 'pass' | 'fail' | 'info' | 'skip'
  terminal: boolean
}

export interface Flag { code: string; message: string }

export interface Recommendation {
  rec_id: string
  resource: ResourceRef
  verdict: Verdict
  reason_code: ReasonCode
  actions: Action[]
  default_option: string
  flags: Flag[]
  current: CostBlock
  target: CostBlock | null
  schedule: Schedule | null
  options: Record<string, Option>
  evidence: Evidence
  replay: Replay | null
  veto: Veto | null
  risk: Risk | null
  reason: string
  explanation_ai: string | null
  formula: string
  trace: TraceStep[]
  alert_ids: string[]
}

export interface RecEnvelope {
  schema_version: string
  generated_at: string
  preset: PresetId
  config_hash: string
  mock_engine: boolean
  data_window: { start: string; end: string; timezone: string }
  items: Recommendation[]
  below_floor: { count: number; monthly_inr: number }
}

// ---------- GET /api/resources, /api/resources/{id}, /api/resources/{id}/metrics ----------

export interface ResourceRow {
  resource_id: string
  name: string
  type: ResourceType
  region: string | null
  env: string | null
  owner_team: string | null
  purpose: string | null
  service_group: string | null
  plan_id: string | null
  vcpu: number | null
  ram_gb: number | null
  disk_gb: number | null
  provisioned_iops: number | null
  bandwidth_mbps: number | null
  state: string
  stopped_since: string | null
  created_at: string
  last_resized_at: string | null
  attached_to: string | null
  unattached_since: string | null
  optimize_policy: string
  tags: string[]
  monthly_inr: number
  has_metrics: boolean
  stats: { cpu_p95: number | null; cpu_p99: number | null; cpu_mean: number | null; mem_p95: number | null; mem_p99: number | null; coverage: number | null } | null
  /** 30 daily p95 values of the main signal (CPU for VMs, disk-used for volumes); null = no data that day */
  daily_p95: (number | null)[] | null
  /** 30 daily CPU maxima (VMs only): shows short peaks a daily p95 hides */
  daily_max: (number | null)[] | null
}

/** Filters GET /api/resources accepts. Missing env / owner tags match `untagged` / `unowned`. */
export interface ResourceFilters { region?: string; env?: string; team?: string; type?: string }

export interface Gap { start: string; end: string; kind: 'missing' | 'flatline'; hours: number }

export type MetricName = 'cpu' | 'mem' | 'disk_used' | 'iops' | 'net_in' | 'net_out'
export type Step = '1h' | '5m'

/** GET /api/resources/{id}/metrics?metric=&step= : one metric, mean + max per step (equal at 5m) */
export interface MetricSeries {
  resource_id: string
  metric: MetricName
  step_seconds: number
  start: string // UTC ISO of the first slot
  mean: (number | null)[]
  max: (number | null)[]
  gaps: Gap[]
}

/** GET /api/resources/{id} : inventory + features + decision trace + data-quality report */
export interface ResourceDetail {
  resource: ResourceRow
  features: {
    cpu: MetricStats | null
    mem: MetricStats | null
    iops_pct: MetricStats | null
    net_pct: MetricStats | null
    disk_used: MetricStats | null
    coverage: number | null
    peak_window_coverage: number | null
    days_of_data: number | null
    cpu_slope: number | null
    disk_slope: number | null
    level_shift_up: number | null
    level_shift_down: number | null
    recurring_peak_days: number | null
    recurring_window: string | null
    p99_excl_top_day: number | null
    mem_std: number | null
    leak_cycles: number | null
    /** hour-of-week p95 CPU in IST, index = day*24 + hour, day 0 = Monday */
    how_p95: (number | null)[] | null
  } | null
  trace: TraceStep[]
  dq: import('./api').DqRow | null
}
