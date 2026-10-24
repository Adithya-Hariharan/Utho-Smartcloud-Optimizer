"""Pydantic v2 copy of the frozen recommendation schema v1.0 (PLAN_final.md §4.5) plus Alert and Summary.

Field names and presence rules follow §4.5 exactly; nullability follows B6/B9a.
"""
from typing import Any, Dict, List, Literal, Optional

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
                "NO_TELEMETRY", "UNKNOWN_PRICE", "ORPHAN_TOO_NEW"},
    "healthy": {"RIGHT_SIZED"},
    "upsize": {"UNDER_PROVISIONED"},
}
METRICS_MAY_BE_NULL = {"NO_TELEMETRY", "HISTORY_TOO_SHORT"}
ACTION_TYPES = Literal["resize", "stop", "delete", "release", "shrink_volume", "schedule", "upsize", "snapshot"]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Resource(Strict):
    resource_id: str
    name: str
    type: Literal["vm", "volume", "ip"]
    env: str
    team: str
    owner: str
    region: str
    purpose: str
    service_group: str
    members: List[str]
    tags: List[str]


class Action(Strict):
    type: ACTION_TYPES
    order: int
    description: str
    requires: List[str]
    reversible: bool
    rollback: Optional[str]


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
    off_hours_per_week: float
    on_hours_per_week: float
    windows: List[Window]
    busy_hours_excluded: List[str]


class Option(Strict):
    monthly_inr_after: int
    saving_inr: int
    formula: str


class MetricSummary(BaseModel):
    model_config = ConfigDict(extra="allow")     # engine may add p90 / p99_5
    p50: Optional[float]
    p95: Optional[float]
    p99: Optional[float]
    max: Optional[float]


class EvidenceMetrics(Strict):
    cpu: MetricSummary
    mem: MetricSummary
    iops_pct: MetricSummary
    net_pct: MetricSummary
    disk_used: MetricSummary


class Evidence(Strict):
    window_days: int
    days_of_data: int
    coverage: float
    peak_window_coverage: float
    percentile_used: Optional[float]
    metrics: Optional[EvidenceMetrics]           # null only for NO_TELEMETRY / HISTORY_TOO_SHORT (§4.5)
    recurring_peak: Optional[Dict[str, Any]]
    naive: Optional[Dict[str, Any]]


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
    value: Any
    threshold: Any
    result: str
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
        if self.evidence.naive is not None and v != "reject":
            raise ValueError("evidence.naive is set only on reject")
        if self.evidence.metrics is None and code not in METRICS_MAY_BE_NULL:
            raise ValueError("evidence.metrics may be null only for NO_TELEMETRY / HISTORY_TOO_SHORT")
        if code in METRICS_MAY_BE_NULL and self.evidence.metrics is not None:
            raise ValueError(f"evidence.metrics must be null for {code}")
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
    preset: str
    config_hash: str
    data_window: DataWindow
    items: List[Recommendation]
    below_floor: BelowFloor


class AlertEvidence(Strict):
    metric: str
    value: Any
    threshold: Any
    window: str


class Alert(Strict):
    alert_id: str
    type: str
    severity: Literal["Critical", "Warning", "Info"]
    resource_id: str
    title: str
    why: str
    evidence: AlertEvidence
    first_seen: str
    occurrences: int
    suggested_action: str


class TrendPoint(Strict):
    label: str
    total_inr: int


class WaterfallStep(Strict):
    label: str
    group: str
    delta_inr: int


class Summary(Strict):
    monthly_before_inr: int
    potential_after_inr: int
    potential_saving_pct: float
    by_env: Dict[str, int]
    by_team: Dict[str, int]
    by_region: Dict[str, int]
    counts: Dict[str, Any]
    bill_trend_6m: List[TrendPoint]
    growth_waterfall: List[WaterfallStep]
