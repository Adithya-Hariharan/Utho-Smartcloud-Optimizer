"""Pydantic v2 recommendation schema v1.0: §4.5 of PLAN_final.md, extended for the frontend
(PLAN_frontend_integration.md §2-§3; frontend/src/types/contract.ts), plus Alert and Summary.
"""
from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, model_validator

Verdict = Literal["recommend", "reject", "flag", "exclude", "healthy", "upsize"]

REASON_CODES = {
    "recommend": {"IDLE", "UNDERUSED", "OFF_HOURS", "ORPHAN_VOLUME", "OVERSIZED_VOLUME", "UNUSED_IP", "STOPPED_VM"},
    "reject": {"VETO_MEMORY", "VETO_IOPS", "VETO_NETWORK", "VETO_GROWTH", "VETO_LEAK", "VETO_RECURRING_PEAK",
               "PEAK_REPLAY_FAILED", "NO_CHEAPER_PLAN"},
    "flag": {"ONE_OFF_PEAK", "WENT_QUIET", "RESERVED_MEMORY", "PEAK_UNDER_OBSERVED", "IDLE_PROD",
             "IDLE_VOLUME_REVIEW"},
    "exclude": {"POLICY_NEVER", "TAG_DR_STANDBY", "TAG_AUTOSCALED", "TAG_SEASONAL", "TAG_ALLOWLISTED_IP",
                "STATEFUL_PROD", "HISTORY_TOO_SHORT", "RECENTLY_RESIZED", "LOW_COVERAGE", "ACTIVE_ANOMALY",
                "NO_TELEMETRY", "UNKNOWN_PRICE", "ORPHAN_TOO_NEW", "STOPPED_RECENTLY", "NOT_IN_INVENTORY"},
    "healthy": {"RIGHT_SIZED", "BELOW_FLOOR"},
    "upsize": {"UNDER_PROVISIONED"},
}
METRICS_MUST_BE_NULL = {"NO_TELEMETRY", "HISTORY_TOO_SHORT", "NOT_IN_INVENTORY"}
ACTION_TYPES = Literal["resize", "stop", "delete", "release", "shrink_volume", "schedule", "upsize", "snapshot"]
TraceResult = Literal["pass", "fail", "info", "skip"]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Resource(Strict):
    resource_id: str
    name: str
    type: Literal["vm", "volume", "ip"]
    env: Optional[str]
    team: Optional[str]
    owner: str
    region: Optional[str]
    purpose: Optional[str]
    service_group: Optional[str]
    members: List[str]
    tags: List[str]
    state: Optional[str]
    plan_id: Optional[str]


class Action(Strict):
    type: ACTION_TYPES
    order: int
    description: str
    requires: List[str]
    reversible: bool
    rollback: str


class Flag(Strict):
    code: str
    message: str


class CostBlock(Strict):
    plan: Optional[str]
    vcpu: Optional[int]
    ram_gb: Optional[int]
    disk_gb: Optional[int]
    compute_inr: int
    storage_inr: int
    ip_inr: int
    monthly_inr: int


class Window(Strict):
    days: str
    start: str
    end: str


class Schedule(Strict):
    timezone: str
    off_hours_per_week: int
    on_hours_per_week: int
    windows: List[Window]
    busy_hours_excluded: List[str]


class Option(Strict):
    monthly_inr_after: int
    saving_inr: int
    formula: str


class MetricStats(Strict):
    mean: float
    p50: float
    p95: float
    p99: float
    max: float


class EvidenceMetrics(Strict):
    cpu: Optional[MetricStats]
    mem: Optional[MetricStats]
    iops_pct: Optional[MetricStats]
    net_pct: Optional[MetricStats]
    disk_used: Optional[MetricStats]


class RecurringPeak(Strict):
    window_ist: str
    days: int


class Naive(Strict):
    action: Literal["resize", "stop", "none", "shrink_volume"]
    target_plan: Optional[str]
    saving_inr: int
    basis: str
    replay_minutes_above_90: Optional[int]


class Evidence(Strict):
    window_days: int
    days_of_data: int
    coverage: float
    peak_window_coverage: Optional[float]
    percentile_used: Literal["p90", "p95", "p99", "p99.5"]
    metrics: Optional[EvidenceMetrics]           # null exactly when the resource has no telemetry
    recurring_peak: Optional[RecurringPeak]
    naive: Optional[Naive]


class ReplayAttempt(Strict):
    plan: str
    minutes_above_90: float
    max_cpu_pct: float
    max_mem_pct: float
    passed: bool


class Replay(Strict):
    limit_minutes_above_90: float
    mem_cap_pct: float
    attempts: List[ReplayAttempt]
    passed: bool
    chosen_plan: Optional[str]
    from_vcpu: int
    from_ram_gb: int


class Veto(Strict):
    signal: str
    metric: str
    value: float
    threshold: float
    comparator: str
    message: str


class RiskPoint(Strict):
    factor: str
    points: int
    detail: str


class Risk(Strict):
    level: Literal["Low", "Medium", "High"]
    score: int
    points: List[RiskPoint]
    confidence: Literal["High", "Medium", "Low"]
    confidence_basis: str


class TraceStep(Strict):
    step: str
    check: str
    value: str
    threshold: str
    result: TraceResult
    terminal: bool


class Recommendation(Strict):
    rec_id: str
    resource: Resource
    verdict: Verdict
    reason_code: str
    actions: List[Action]
    default_option: str
    flags: List[Flag]
    current: CostBlock
    target: Optional[CostBlock]
    schedule: Optional[Schedule]
    options: Dict[str, Option]
    evidence: Evidence
    replay: Optional[Replay]
    veto: Optional[Veto]
    risk: Optional[Risk]
    reason: str
    explanation_ai: Optional[str]
    formula: str
    trace: List[TraceStep]
    alert_ids: List[str]

    @model_validator(mode="after")
    def presence_rules(self):
        v, code = self.verdict, self.reason_code
        if code not in REASON_CODES[v]:
            raise ValueError(f"reason_code {code} is not valid for verdict {v}")
        if "none" not in self.options:
            raise ValueError("options must always contain 'none'")
        if self.default_option not in self.options:
            raise ValueError("default_option must be a key of options")
        if (self.veto is not None) != (v == "reject"):
            raise ValueError("veto is required on reject and only on reject")
        if self.risk is not None and v not in ("recommend", "upsize"):
            raise ValueError("risk is set only on recommend and upsize")
        if v in ("recommend", "upsize") and self.risk is None:
            raise ValueError("risk is required on recommend and upsize")
        if self.evidence.naive is not None and v not in ("reject", "flag"):
            raise ValueError("evidence.naive is set only on reject and flag")
        if code in METRICS_MUST_BE_NULL and self.evidence.metrics is not None:
            raise ValueError(f"evidence.metrics must be null for {code}")
        if self.replay is not None and not self.replay.attempts:
            raise ValueError("replay is null or has at least one attempt")
        if sum(s.terminal for s in self.trace) != 1:
            raise ValueError("exactly one trace step is terminal")
        return self


class DataWindow(Strict):
    start: str
    end: str
    timezone: str


class BelowFloor(Strict):
    count: int
    monthly_inr: int


class RecommendationEnvelope(Strict):
    schema_version: str
    generated_at: str
    preset: Literal["max_savings", "balanced", "default", "max_performance"]
    config_hash: str
    mock_engine: bool
    data_window: DataWindow
    items: List[Recommendation]
    below_floor: BelowFloor


class TimeWindow(Strict):
    start: str
    end: str


ALERT_TYPES = Literal["spike", "level_shift", "possible_compromise", "capacity", "memory_leak", "team_cost_jump",
                      "under_provisioned", "monitoring_missing", "orphan_series"]


class AlertEvidence(Strict):
    metric: str
    value: Union[float, int, str, None]
    threshold: Union[float, int, str]
    window: Optional[TimeWindow]


class Alert(Strict):
    alert_id: str
    type: ALERT_TYPES
    severity: Literal["critical", "warning", "info"]
    resource_id: Optional[str]
    name: str
    title: str
    why: str
    evidence: AlertEvidence
    window: Optional[TimeWindow]
    first_seen: str
    occurrences: int
    suggested_action: str


class AlertsResponse(Strict):
    mock_engine: bool
    items: List[Alert]


class SplitTotals(Strict):
    monthly_before_inr: int
    potential_after_inr: int


class GrowthDelta(Strict):
    key: str
    first30_inr: int
    last30_inr: int
    delta_inr: int


class NewResource(Strict):
    resource_id: str
    name: str
    team: str
    env: str
    type: str
    created_at: str
    monthly_inr: int


class Waterfall(Strict):
    first30: Dict[str, Union[str, int]]
    last30: Dict[str, Union[str, int]]
    growth_ratio: float
    by_env: List[GrowthDelta]
    by_team: List[GrowthDelta]
    by_age: List[GrowthDelta]
    new_resources: List[NewResource]


class BillTrend(Strict):
    dates: List[str]
    total: List[float]
    by_env: Dict[str, List[float]]
    by_team: Dict[str, List[float]]


class Counts(Strict):
    vm: int
    volume: int
    ip: int
    verdicts: Dict[str, int]


class Summary(Strict):
    monthly_before_inr: int
    potential_after_inr: int
    potential_saving_pct: float
    by_env: Dict[str, SplitTotals]
    by_team: Dict[str, SplitTotals]
    by_region: Dict[str, SplitTotals]
    counts: Counts
    bill_trend_6m: BillTrend
    growth_waterfall: Waterfall
