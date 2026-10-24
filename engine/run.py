"""python -m engine.run [--preset default]  ->  data/recommendations.json (schema v1.0, PLAN.md 4.5)
                                                + data/alerts.json (schema 'Alert'), linked through alert_ids.

Uses the logic chosen by the checkpointed selection (engine/selection.json)."""
import argparse
import json

from . import alerts as AL
from . import data as D
from . import output
from . import pipeline as PL
from .config import Config
from .select import SEL, prior_selection

OUT = D.DATA / "recommendations.json"
ALERTS = D.DATA / "alerts.json"


def selection():
    return json.loads(SEL.read_text()) if SEL.exists() else prior_selection()


def build(preset="default", with_alerts=True, data=None):
    cfg = Config(preset)
    data = data or D.load(cfg)
    ctx, res = PL.run(data, cfg, selection())
    alerts = AL.build(ctx, res) if with_alerts else []
    by_res = {}
    for a in alerts:
        if a["resource_id"]:
            by_res.setdefault(a["resource_id"], []).append(a["alert_id"])
    env = output.envelope(ctx, res)
    for item in env["items"]:
        item["alert_ids"] = by_res.get(item["resource"]["resource_id"], [])
    return env, ctx, res, alerts


def headline(env):
    before = sum(it["options"]["none"]["monthly_inr_after"] for it in env["items"])
    saving = sum(it["options"][it["default_option"]]["saving_inr"] for it in env["items"]
                 if it["verdict"] == "recommend" and it["default_option"])
    return before, saving


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--preset", default="default")
    a = ap.parse_args()
    env, ctx, res, alerts = build(a.preset)
    OUT.write_text(json.dumps(env, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    ALERTS.write_text(json.dumps(AL.envelope(ctx, alerts), indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    counts = {}
    for it in env["items"]:
        counts[it["verdict"]] = counts.get(it["verdict"], 0) + 1
    before, saving = headline(env)
    print(f"{OUT.name}: {len(env['items'])} items {counts} | bill Rs {before:,}/month | "
          f"potential saving Rs {saving:,} ({saving / before:.1%}) | {ALERTS.name}: {len(alerts)} alerts "
          f"{AL.envelope(ctx, alerts)['counts']}")


if __name__ == "__main__":
    main()
