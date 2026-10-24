"""Every truth.csv row: verdict + reason code + action. Rows whose label contradicts the (fitted) data are
xfail(strict=True) with the evidence in engine/disputes.py and REASONING.md -> if the engine ever starts
agreeing with them the test fails, so a dispute can never silently disappear."""
import pandas as pd
import pytest

from engine.data import load_truth
from engine.disputes import DISPUTES, active

TRUTH = load_truth()


def _action(item):
    return item["default_option"] if item["verdict"] in ("recommend", "upsize") and item["default_option"] else "none"


@pytest.mark.parametrize("row", TRUTH.to_dict("records"), ids=list(TRUTH["name"]))
def test_truth_row(row, engine_run, request):
    if row["name"] in DISPUTES and active():
        request.node.add_marker(pytest.mark.xfail(strict=True, reason=DISPUTES[row["name"]]["summary"]))
    item = engine_run["by_id"][row["resource_id"]]
    assert (item["verdict"], item["reason_code"]) == (row["expected_verdict"], row["expected_reason_code"])
    assert _action(item) == row["expected_action"]
