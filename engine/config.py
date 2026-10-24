"""Engine configuration: every number comes from config.yaml (see REASONING.md, numbers ledger)."""
import copy
import hashlib
import json
from pathlib import Path

import yaml

PATH = Path(__file__).resolve().parent / "config.yaml"
_RAW = yaml.safe_load(PATH.read_text(encoding="utf-8"))


def numeric_keys(raw=None):
    """All dotted keys whose leaf is {value: number}, excluding presets/meta."""
    raw = _RAW if raw is None else raw
    out = []
    for sec, body in raw.items():
        if sec in ("meta", "presets") or not isinstance(body, dict):
            continue
        for k, v in body.items():
            if isinstance(v, dict) and "value" in v:
                out.append(f"{sec}.{k}")
    return out


class Config:
    """Read-only view with optional overrides (perturbations) and a preset."""

    def __init__(self, preset="default", overrides=None):
        self.raw = _RAW
        self.preset_name = preset
        self.preset = dict(_RAW["presets"][preset])
        self.overrides = dict(overrides or {})

    def __call__(self, key):
        if key in self.overrides:
            return self.overrides[key]
        sec, name = key.split(".", 1)
        return self.raw[sec][name]["value"]

    def meta(self, key):
        return self.raw["meta"][key]

    def t(self, name):
        return self("time_units." + name)

    def with_overrides(self, extra):
        return Config(self.preset_name, {**self.overrides, **extra})

    def perturbed(self, section, factor):
        """Multiply every numeric threshold of `section` by `factor` (robustness test)."""
        extra = {}
        for key in numeric_keys():
            if key.startswith(section + "."):
                v = self(key)
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    nv = v * factor
                    if "percentile" in key:          # a percentile cannot exceed 100
                        nv = min(nv, 100)
                    extra[key] = nv
        return self.with_overrides(extra)

    def hash(self):
        blob = json.dumps({"raw": self.raw, "preset": self.preset_name, "ov": self.overrides}, sort_keys=True,
                          default=str)
        return hashlib.sha256(blob.encode()).hexdigest()[:12]


def entry(key):
    sec, name = key.split(".", 1)
    return copy.deepcopy(_RAW[sec][name])
