"""Engine parameters for a preset (plan section 7). Only `default` is enabled in the MVP."""
from dataclasses import dataclass

PCT_KEY = {90: "p90", 95: "p95", 99: "p99", 99.5: "p99_5"}


@dataclass(frozen=True)
class Params:
    preset: str
    pct_prod: float
    pct_nonprod: float
    cpu_target_prod: float
    cpu_target_nonprod: float
    mem_target: float
    mem_cap: float
    replay_limit_prod: float
    replay_limit_nonprod: float

    def pct(self, prod):
        return self.pct_prod if prod else self.pct_nonprod

    def pct_key(self, prod):
        return PCT_KEY[self.pct(prod)]

    def cpu_target(self, prod):
        return self.cpu_target_prod if prod else self.cpu_target_nonprod

    def replay_limit(self, prod):
        return self.replay_limit_prod if prod else self.replay_limit_nonprod


class PresetNotEnabled(ValueError):
    pass


def params_for(cfg, preset="default"):
    presets = cfg.raw["presets"]
    if preset not in presets or not presets[preset].get("enabled"):
        raise PresetNotEnabled(preset)
    t = lambda k: cfg.get(f"thresholds.{k}")
    return Params(preset=preset, pct_prod=t("percentile_prod"), pct_nonprod=t("percentile_nonprod"),
                  cpu_target_prod=t("cpu_target_prod_pct"), cpu_target_nonprod=t("cpu_target_nonprod_pct"),
                  mem_target=t("mem_target_pct"), mem_cap=t("mem_hard_cap_pct"),
                  replay_limit_prod=t("replay_limit_minutes_prod"),
                  replay_limit_nonprod=t("replay_limit_minutes_nonprod"))
