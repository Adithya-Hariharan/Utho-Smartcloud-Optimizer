"""truth.csv rows the selected engine disagrees with, and why the engine is kept as is.

Each was checked against the measured evidence (engine run on the committed data). The common cause for the
first group: these planted VMs were labelled for the hand-set curves, then the generator's fitted noise/drift
(commit 7b73730, see data/DATASET.md 'Pinned planted cases') was applied to them too, and the data moved.
Used by tests/test_engine_truth.py (xfail strict) and engine/REASONING.md section 5."""

DISPUTES = {
    "prod-api-02": {
        "label": "healthy / RIGHT_SIZED", "engine": "upsize / UNDER_PROVISIONED",
        "summary": "The 30-min mean CPU reaches 100% on 7 of 30 days and p95 is 89% on B3. Under the fitted noise "
                   "this VM is saturated, not right-sized; the label was written for the hand-set curve (p95 ~70%). "
                   "Fix belongs in the data (pin it on b1_adi), not in the engine.",
    },
    "prod-api-04": {
        "label": "healthy / RIGHT_SIZED (+ capacity alert)", "engine": "upsize / UNDER_PROVISIONED",
        "summary": "The VM is growing (the planted trend) and its 30-min peak already touched 100% and 93% on two "
                   "days. Upsizing a growing, saturating VM is the safer recommendation; the label expected the "
                   "growth to stay below saturation inside the window.",
    },
    "prod-web-11a": {
        "label": "recommend / UNDERUSED (resize)", "engine": "reject / PEAK_REPLAY_FAILED",
        "summary": "Service group web-frontend is sized on its busiest member. 11a's busiest day peaks at 61% (30-min "
                   "mean); replayed on B2 that is 70 min above 90% (prod budget 0). Members of a load-balanced group "
                   "must stay the same size, so none shrink. With hand-set noise the group fitted B2.",
    },
    "prod-web-11b": {
        "label": "recommend / UNDERUSED (resize)", "engine": "reject / PEAK_REPLAY_FAILED",
        "summary": "Same group decision as 11a; 11b alone has p99 48% (not underused at P < 40) and a 68% peak day.",
    },
    "prod-web-11c": {
        "label": "recommend / UNDERUSED (resize)", "engine": "reject / PEAK_REPLAY_FAILED",
        "summary": "11c alone would pass replay on B2 (0 min above 90%), but the group stays together because 11a "
                   "cannot shrink. Resizing one member of a load-balanced pool would skew the balancer.",
    },
    "staging-demo-10": {
        "label": "healthy / RIGHT_SIZED", "engine": "reject / PEAK_REPLAY_FAILED",
        "summary": "Averages 10% (an average-based tool would cut B2 -> S1 and save Rs 2,121) but office-hours peaks "
                   "replay at 8,410 min above 90% on S1. keep_running forbids scheduling, not evaluation, so the VM "
                   "belongs in the Rejections panel ('checked and kept') rather than silently 'healthy'.",
    },
    "prod-checkout-34": {
        "label": "healthy / RIGHT_SIZED", "engine": "reject / NO_CHEAPER_PLAN",
        "summary": "A resampled real right-sized VM whose mean landed at 19.3% (< 20%, so it looks wasteful). Its "
                   "memory p99 is 49% of 32 GB: 21 GB needed after headroom, and no cheaper plan has that much RAM. "
                   "'Checked and kept' is the accurate status; the label used the archetype name only.",
    },
    "staging-batch-68": {
        "label": "reject / VETO_RECURRING_PEAK", "engine": "recommend / OFF_HOURS",
        "summary": "Non-prod batch VM idle except 01:00-03:00. The recurring peak correctly blocks any resize, but an "
                   "off-hours schedule that keeps 01:00-03:00 on saves 148 h/week safely (0 unsafe in the backtest). "
                   "This is exactly dev-etl-04's case, whose label is OFF_HOURS; the two labels contradict each other "
                   "and the engine follows one principle: a recurring peak blocks shrinking, not scheduling around it.",
    },
    "dev-batch-69": {
        "label": "reject / VETO_RECURRING_PEAK", "engine": "recommend / OFF_HOURS",
        "summary": "Same as staging-batch-68 (off 149 h/week, nightly window kept on).",
    },
}
