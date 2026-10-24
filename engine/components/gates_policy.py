"""CP3 - policy / tag / inventory gates. Pure inventory logic: no metrics are read except 'are there any'."""
from .base import age_days, finding, has_tag, trace_only

C = "gates_policy"
ENV_PREFIXES = ("prod", "staging", "dev")


def _common(ctx, r, infer):
    out = []
    if r.inv is None:
        return [finding(C, "NOT_IN_INVENTORY", "exclude", "resource in inventory", "no", "yes",
                        message="metrics exist but no inventory row: cannot price or own it")]
    inv = r.inv
    raw_env = inv.get("env") or ""
    name = inv.get("name") or ""
    prefix = name.split("-")[0]
    if not raw_env:
        if infer and prefix in ENV_PREFIXES:
            r.env = prefix
            r.flags.append({"code": "UNTAGGED_ENV", "message": f"env tag missing; inferred '{prefix}' from name"})
        else:
            r.env = "prod"
            r.flags.append({"code": "UNTAGGED_ENV", "message": "env tag missing: treated as prod (safest)"})
    if not (inv.get("owner_team") or ""):
        r.flags.append({"code": "UNOWNED", "message": "owner missing: routed to 'unowned'"})
    if raw_env and prefix in ENV_PREFIXES and prefix != raw_env:
        r.flags.append({"code": "TAG_NAME_CONFLICT", "message": f"name says '{prefix}', tag says '{raw_env}': tag trusted"})

    if r.type == "vm" and inv.get("plan_id") not in ctx.data.plans:
        out.append(finding(C, "UNKNOWN_PRICE", "exclude", "plan in price catalogue", inv.get("plan_id"), "catalogue",
                           message="plan not in the price list: we never guess a price"))
    stopped = r.type == "vm" and r.state == "stopped"
    if r.type == "vm" and not stopped and r.arr is None:
        out.append(finding(C, "NO_TELEMETRY", "exclude", "metrics present", "none", "any",
                           message="monitoring agent missing: no metrics at all"))
    for tag, code in (("dr_standby", "TAG_DR_STANDBY"), ("autoscaled", "TAG_AUTOSCALED"),
                      ("seasonal_peak", "TAG_SEASONAL"), ("allowlisted_ip", "TAG_ALLOWLISTED_IP")):
        if has_tag(r, tag):
            out.append(finding(C, code, "exclude", f"tag {tag}", "present", "absent",
                               message=f"tag '{tag}': only human context can decide this resource"))
    if (inv.get("optimize_policy") or "") == "never":
        out.append(finding(C, "POLICY_NEVER", "exclude", "optimize_policy", "never", "default"))
    if has_tag(r, "stateful") and r.env == "prod":
        out.append(finding(C, "STATEFUL_PROD", "exclude", "stateful and prod", "yes", "no",
                           message="stateful production: does not recover gracefully when squeezed"))
    if stopped:
        days = age_days(inv.get("stopped_since"), ctx.now)
        lim = ctx.cfg("gates_policy.stopped_recent_days")
        if days < lim:
            out.append(finding(C, "STOPPED_RECENTLY", "exclude", "days stopped", days, lim,
                               message="stopped recently: treated as maintenance"))
        else:
            out.append(trace_only(C, "days stopped", days, lim, True))
    return out


def a_table(ctx, r):
    """Tag/policy table + price check + missing env -> prod."""
    r.findings += _common(ctx, r, infer=False)


def b_infer(ctx, r):
    """a + infer a missing env from the name prefix (prod-/staging-/dev-)."""
    r.findings += _common(ctx, r, infer=True)


CANDIDATES = {
    "a_table": {"fn": a_table, "params": 1, "prior": 9, "desc": "tag/policy table, price check, missing env treated as prod"},
    "b_infer": {"fn": b_infer, "params": 2, "prior": 5, "desc": "a + guess a missing env from the name prefix"},
}
