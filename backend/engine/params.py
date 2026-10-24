"""Engine parameters for a preset (plan section 7 preset table, values in config.yaml `presets`)."""
from dataclasses import dataclass

PCT_KEY = {90: "p90", 95: "p95", 99: "p99", 99.5: "p99_5"}


@dataclass(frozen=True)
class Params:
    preset: str
    label: str
    pct_prod: float
    pct_nonprod: float
    cpu_target_prod: float
    cpu_target_nonprod: float
    mem_target: float
    mem_cap: float
    replay_limit_prod: float
    replay_limit_nonprod: float
    underused_cpu_pct: float          # a VM is a resize candidate when CPU P < this and memory P < underused_mem_pct
    underused_mem_pct: float
    shrinkable_mean_cpu_pct: float    # ... or when its mean CPU is below this ("looks wasteful on average")

    def pct(self, prod):
        return self.pct_prod if prod else self.pct_nonprod

    def pct_key(self, prod):
        return PCT_KEY[self.pct(prod)]

    def pct_label(self, prod):
        """'p99', 'p95', 'p90', 'p99.5' (evidence.percentile_used)."""
        return f"p{self.pct(prod):g}"

    def cpu_target(self, prod):
        return self.cpu_target_prod if prod else self.cpu_target_nonprod

    def replay_limit(self, prod):
        return self.replay_limit_prod if prod else self.replay_limit_nonprod


class PresetNotEnabled(ValueError):
    pass


def enabled_presets(cfg):
    return [k for k, v in cfg.raw["presets"].items() if v.get("enabled")]


def params_for(cfg, preset="default"):
    presets = cfg.raw["presets"]
    if preset not in presets or not presets[preset].get("enabled"):
        raise PresetNotEnabled(preset)
    p = presets[preset]
    t = lambda k: cfg.get(f"thresholds.{k}")
    return Params(preset=preset, label=p["label"], pct_prod=p["pct_prod"], pct_nonprod=p["pct_nonprod"],
                  cpu_target_prod=p["cpu_target_prod"], cpu_target_nonprod=p["cpu_target_nonprod"],
                  mem_target=t("mem_target_pct"), mem_cap=t("mem_hard_cap_pct"),
                  replay_limit_prod=p["replay_limit_prod"], replay_limit_nonprod=p["replay_limit_nonprod"],
                  underused_cpu_pct=p["underused_cpu_pct"], underused_mem_pct=p["underused_mem_pct"],
                  shrinkable_mean_cpu_pct=p["shrinkable_mean_cpu_pct"])
