"""CP12 - turn the evidence board (all findings) into one verdict.

a_ladder      PLAN.md 7 first-match ladder: walk the stages in order, stop at the first decisive finding;
              later findings are never shown.
b_precedence  every component runs; the verdict is the highest class in PRECEDENCE, the most specific code
              within it (CODE_ORDER); every other fired signal is listed in flags[] and the trace."""
from .base import CODE_ORDER, PRECEDENCE, VERDICT_OF

STAGES = ["clean", "gates_policy", "gates_data", "noncompute", "sizing:upsize", "vetoes", "peaks", "patterns", "candidates",
          "cost", "sizing", "healthy"]


def _stage(f):
    if f["comp"] == "sizing" and f["kind"] == "upsize":
        return STAGES.index("sizing:upsize")
    if f["kind"] == "healthy" and f["comp"] != "noncompute":
        return STAGES.index("healthy")
    return STAGES.index(f["comp"]) if f["comp"] in STAGES else len(STAGES)


def _rank(f):
    code = f["code"]
    return CODE_ORDER.index(code) if code in CODE_ORDER else len(CODE_ORDER)


def _decide(r, primary, shown):
    r.primary = primary
    r.verdict = VERDICT_OF[primary["kind"]]
    r.reason_code = primary["code"]
    r.shown = shown
    r.veto = None
    if primary["kind"] in ("reject", "soft_reject"):
        r.veto = {"signal": primary["code"].replace("VETO_", "").lower(), "metric": primary["check"],
                  "value": primary["value"], "threshold": primary["threshold"],
                  "comparator": ">=" if primary["code"] in ("VETO_RECURRING_PEAK",) else ">",
                  "message": primary["message"]}


def a_ladder(ctx, r):
    dec = [f for f in r.findings if f["kind"] != "info"]
    dec.sort(key=lambda f: (_stage(f), _rank(f)))
    primary = dec[0]
    cut = _stage(primary)
    shown = [f for f in r.findings if _stage(f) <= cut and (f["kind"] == "info" or f is primary)]
    _decide(r, primary, shown)


def b_precedence(ctx, r):
    dec = [f for f in r.findings if f["kind"] != "info"]
    dec.sort(key=lambda f: (PRECEDENCE.index(f["kind"]), _rank(f)))
    primary = dec[0]
    _decide(r, primary, list(r.findings))
    for f in dec[1:]:
        if f["kind"] not in ("healthy", "recommend"):
            r.flags.append({"code": f["code"], "message": f"also: {f['message'] or f['check']}"})


CANDIDATES = {
    "a_ladder": {"fn": a_ladder, "params": 1, "prior": 6, "desc": "first-match ladder in stage order (PLAN.md 7)"},
    "b_precedence": {"fn": b_precedence, "params": 2, "prior": 9, "desc": "evidence board + published precedence; all fired signals listed"},
}
