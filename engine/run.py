"""python -m engine.run [--preset default]  ->  data/recommendations.json (schema v1.0, PLAN.md 4.5)

Uses the logic chosen by the checkpointed selection (engine/selection.json)."""
import argparse
import json

from . import data as D
from . import output
from . import pipeline as PL
from .config import Config
from .select import SEL, prior_selection

OUT = D.DATA / "recommendations.json"


def selection():
    return json.loads(SEL.read_text()) if SEL.exists() else prior_selection()


def build(preset="default"):
    cfg = Config(preset)
    data = D.load(cfg)
    ctx, res = PL.run(data, cfg, selection())
    return output.envelope(ctx, res)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--preset", default="default")
    a = ap.parse_args()
    env = build(a.preset)
    OUT.write_text(json.dumps(env, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    counts = {}
    for it in env["items"]:
        counts[it["verdict"]] = counts.get(it["verdict"], 0) + 1
    before = sum(it["options"]["none"]["monthly_inr_after"] for it in env["items"])
    saving = sum(it["options"][it["default_option"]]["saving_inr"] for it in env["items"]
                 if it["verdict"] == "recommend" and it["default_option"])
    print(f"{OUT.name}: {len(env['items'])} items {counts} | bill Rs {before:,}/month | "
          f"potential saving Rs {saving:,} ({saving / before:.1%})")


if __name__ == "__main__":
    main()
