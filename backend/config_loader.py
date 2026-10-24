"""Loads config.yaml (the single source of truth, PLAN_final.md B7) and fingerprints it."""
import hashlib
import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import pandas as pd
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = REPO_ROOT / "config.yaml"


def _unwrap(node):
    """{value, why, source} -> value; recurses through plain mappings."""
    if isinstance(node, dict):
        if "value" in node and set(node) <= {"value", "why", "source"}:
            return node["value"]
        return {k: _unwrap(v) for k, v in node.items()}
    return node


@dataclass(frozen=True)
class Config:
    raw: dict
    hash: str

    def get(self, dotted):
        """Value at a dotted path, with {value, why, source} unwrapped."""
        node = self.raw
        for part in dotted.split("."):
            node = node[part]
        return _unwrap(node)

    @property
    def tz(self):
        return self.raw["window"]["timezone"]

    @property
    def window_start(self):
        return pd.Timestamp(self.raw["window"]["start"]).tz_convert(self.tz)

    @property
    def window_end(self):
        return pd.Timestamp(self.raw["window"]["end"]).tz_convert(self.tz)

    @property
    def now(self):
        return pd.Timestamp(self.raw["window"]["now"]).tz_convert(self.tz)

    @property
    def slots(self):
        return int(self.raw["window"]["slots"])

    @property
    def plans(self):
        return self.raw["pricing"]["plans"]

    def plan_price(self, plan_id):
        """Monthly ₹ for a catalogue or billing-only legacy plan; None if unknown."""
        if plan_id in self.plans:
            return int(self.plans[plan_id]["monthly_inr"])
        legacy = self.get("pricing.legacy_plan_rates")
        return int(legacy[plan_id]) if plan_id in legacy else None


def config_hash(raw):
    canonical = json.dumps(raw, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def load_config(path=CONFIG_PATH):
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return Config(raw=raw, hash=config_hash(raw))


@lru_cache(maxsize=1)
def get_config():
    return load_config()
