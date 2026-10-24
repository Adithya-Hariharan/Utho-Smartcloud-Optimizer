"""POST /api/export: accepted changes as a file (csv | md | sh | tf).

Content follows the frontend's former in-browser export (docs/reference/export_reference.ts); every figure comes
from the option the user accepted. `sh` is a DRY RUN by default, and `cloudctl` / the Terraform provider are
placeholders for the real provider tooling.
"""
import re

from ..cost.model import format_inr

FORMATS = {"csv": ("smartcloud-accepted.csv", "text/csv"), "md": ("smartcloud-accepted.md", "text/markdown"),
           "sh": ("apply.sh", "text/x-shellscript"), "tf": ("smartcloud-plan.tf", "text/plain")}
ACTION_LABEL = {"snapshot": "Snapshot", "delete": "delete", "release": "Release IP", "stop": "Stop", "resize": "Resize",
                "shrink_volume": "Shrink volume", "upsize": "Upsize", "schedule": "Schedule"}


class ExportError(ValueError):
    pass


def option_label(key, item):
    if key == "none":
        return "No change"
    parts = []
    for i, a in enumerate(key.split("+")):
        s = ACTION_LABEL[a]
        if a in ("resize", "upsize") and item.get("target"):
            s += f" {item['current']['plan']} → {item['target']['plan']}"
        parts.append(s if i == 0 else s.lower())
    return " + ".join(parts)


def resolve(st, accepted):
    """[{rec_id, option_key}] -> [(item, key, preset)], each rec_id looked up in the preset it names."""
    out = []
    for a in accepted:
        if not isinstance(a, dict) or "rec_id" not in a or "option_key" not in a:
            raise ExportError("each accepted entry needs rec_id and option_key")
        m = re.fullmatch(r"REC-(.+)-([a-z_]+)", a["rec_id"])
        if not m or m.group(2) not in st.by_id or m.group(1) not in st.by_id[m.group(2)]:
            raise ExportError(f"unknown rec_id {a['rec_id']}")
        item = st.by_id[m.group(2)][m.group(1)]
        if a["option_key"] not in item["options"]:
            raise ExportError(f"{a['rec_id']} has no option {a['option_key']}")
        out.append((item, a["option_key"], m.group(2)))
    return sorted(out, key=lambda x: -x[0]["options"][x[1]]["saving_inr"])


def _csv_cell(v):
    s = str(v)
    return f'"{s.replace(chr(34), chr(34) * 2)}"' if re.search(r'[",\n]', s) else s


def to_csv(rows):
    head = ["resource_id", "name", "env", "team", "region", "action", "current_plan", "target_plan",
            "monthly_before_inr", "monthly_after_inr", "saving_inr", "risk", "formula"]
    lines = [head]
    for item, key, _ in rows:
        r, o = item["resource"], item["options"][key]
        lines.append([r["resource_id"], r["name"], r["env"] or "untagged", r["team"] or "unowned", r["region"] or "",
                      key, item["current"]["plan"] or "", (item["target"] or {}).get("plan") or "",
                      item["current"]["monthly_inr"], o["monthly_inr_after"], o["saving_inr"],
                      (item["risk"] or {}).get("level", ""), o["formula"]])
    return "\n".join(",".join(_csv_cell(c) for c in row) for row in lines) + "\n"


def to_markdown(st, rows):
    preset = rows[0][2] if rows else "default"
    items = st.by_id[preset]
    chosen = {item["resource"]["resource_id"]: key for item, key, _ in rows}
    before = sum(i["current"]["monthly_inr"] for i in items.values())
    after = sum(i["options"][chosen.get(rid, "none")]["monthly_inr_after"] for rid, i in items.items())
    fixes = sum(-item["options"][key]["saving_inr"] for item, key, _ in rows if item["verdict"] == "upsize")
    w = st.runs[preset]["data_window"]
    label = st.cfg.raw["presets"][preset]["label"]
    out = ["# SmartCloud Optimizer: accepted changes", "",
           f"Preset **{label}** · data window {w['start'][:10]} to {w['end'][:10]} (IST)", "",
           "| | Monthly |", "|---|---:|", f"| Before | {format_inr(before)} |", f"| After | {format_inr(after)} |",
           f"| Saving | {format_inr(before - after)} ({(before - after) / before * 100 if before else 0:.1f}%) |"]
    if fixes:
        out.append(f"| Risk fixes (upsizes) | +{format_inr(fixes)} |")
    out += ["", "| Resource | Env | Action | Saving / mo | Risk | Formula |", "|---|---|---|---:|---|---|"]
    for item, key, _ in rows:
        o = item["options"][key]
        out.append(f"| {item['resource']['name']} | {item['resource']['env'] or 'untagged'} | {option_label(key, item)} | "
                   f"{format_inr(o['saving_inr'])} | {(item['risk'] or {}).get('level', '—')} | {o['formula'].replace('|', '/')} |")
    return "\n".join(out + [""])


def _volume_target_gb(item, key):
    m = re.search(r"→ (\d+) GB", item["options"][key]["formula"])
    return m.group(1) if m else "100"


def to_script(rows):
    out = ["#!/usr/bin/env bash", "# SmartCloud Optimizer: apply accepted changes.",
           "# DRY RUN by default; set DRY_RUN=0 to execute. `cloudctl` is a placeholder for your provider CLI.",
           "# Prod changes: apply in a maintenance window. Snapshots are always taken before delete.",
           "set -euo pipefail", 'DRY_RUN="${DRY_RUN:-1}"',
           'run() { if [ "$DRY_RUN" = "1" ]; then echo "[dry-run] $*"; else "$@"; fi; }', ""]
    for n, (item, key, _) in enumerate(rows, 1):
        rid, r = item["resource"]["resource_id"], item["resource"]
        o = item["options"][key]
        out.append(f"# {n}. {r['name']} ({item['rec_id']} {key}): {option_label(key, item)} · saves "
                   f"{format_inr(o['saving_inr'])}/mo · risk {(item['risk'] or {}).get('level', '—')}")
        for a in key.split("+"):
            if a == "snapshot":
                out.append(f"run cloudctl snapshot create --resource {rid} --name pre-optimizer-{rid}")
            elif a == "stop":
                out += [f"run cloudctl vm stop --id {rid}", f"#   rollback: cloudctl vm start --id {rid}"]
            elif a == "delete":
                out += [f'echo "hold 14 days, then: cloudctl {r["type"]} delete --id {rid}"',
                        f"#   rollback: restore from snapshot pre-optimizer-{rid}"]
            elif a == "release":
                out.append(f"run cloudctl ip release --id {rid}")
            elif a in ("resize", "upsize"):
                out += [f"run cloudctl vm resize --id {rid} --plan {item['target']['plan']}",
                        f"#   rollback: cloudctl vm resize --id {rid} --plan {item['current']['plan']}"]
            elif a == "shrink_volume":
                out += [f"run cloudctl volume migrate --id {rid} --size-gb {_volume_target_gb(item, key)}",
                        "#   rollback: keep the old volume until verified"]
            elif a == "schedule":
                for w in (item["schedule"] or {}).get("windows", []):
                    out.append(f'run cloudctl schedule add --id {rid} --tz Asia/Kolkata --off "{w["days"]} {w["start"]}" '
                               f'--on "{w["end"]}"')
        out.append("")
    return "\n".join(out)


def to_terraform(rows):
    out = ["# SmartCloud Optimizer: accepted changes as a Terraform-style plan.",
           "# PLACEHOLDER provider `smartcloud`: map these blocks onto your real provider's resources.", ""]
    for n, (item, key, _) in enumerate(rows, 1):
        rid, r = item["resource"]["resource_id"], item["resource"]
        name = re.sub(r"[^a-z0-9_]", "_", r["name"].lower())
        out.append(f"# {n}. {r['name']} ({item['rec_id']} {key}): {option_label(key, item)} · saves "
                   f"{format_inr(item['options'][key]['saving_inr'])}/mo")
        acts = set(key.split("+"))
        if acts & {"resize", "upsize"}:
            out += [f'resource "smartcloud_vm" "{name}" {{', f'  id   = "{rid}"', f'  plan = "{item["target"]["plan"]}"'
                    f'  # was {item["current"]["plan"]}']
            if "schedule" in acts:
                out += [f'  schedule = [{", ".join(chr(34) + w["days"] + " " + w["start"] + "-" + w["end"] + chr(34) for w in item["schedule"]["windows"])}]']
            out.append("}")
        elif "schedule" in acts:
            out += [f'resource "smartcloud_vm_schedule" "{name}" {{', f'  vm_id    = "{rid}"', '  timezone = "Asia/Kolkata"',
                    f'  off      = [{", ".join(chr(34) + w["days"] + " " + w["start"] + "-" + w["end"] + chr(34) for w in item["schedule"]["windows"])}]',
                    "}"]
        elif "shrink_volume" in acts:
            out += [f'resource "smartcloud_volume" "{name}" {{', f'  id      = "{rid}"',
                    f'  size_gb = {_volume_target_gb(item, key)}  # migrate: no in-place shrink', "}"]
        else:
            for a in sorted(acts):
                out.append(f"# {a}: {rid} (run outside Terraform; snapshot first where listed)")
        out.append("")
    return "\n".join(out)


def export(st, accepted, fmt):
    if fmt not in FORMATS:
        raise ExportError(f"format must be one of {sorted(FORMATS)}")
    rows = resolve(st, accepted)
    body = {"csv": lambda: to_csv(rows), "md": lambda: to_markdown(st, rows), "sh": lambda: to_script(rows),
            "tf": lambda: to_terraform(rows)}[fmt]()
    filename, media = FORMATS[fmt]
    return body, filename, media
