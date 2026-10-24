import json

from engine import data as D, output, pipeline as PL
from engine.checkpoints import SCHEMA_KEYS
from engine.config import Config
from engine.run import selection

ENVELOPE = ["schema_version", "generated_at", "preset", "config_hash", "data_window", "items", "below_floor"]


def test_envelope(engine_run):
    env = engine_run["env"]
    assert list(env) == ENVELOPE
    assert env["schema_version"] == "1.0"
    assert set(env["data_window"]) == {"start", "end", "timezone"}


def test_every_object_has_schema_keys(engine_run):
    for i in engine_run["env"]["items"]:
        assert list(i) == SCHEMA_KEYS, i["rec_id"]
        assert i["verdict"] in ("recommend", "reject", "flag", "exclude", "healthy", "upsize")
        assert "none" in i["options"]


def test_presence_matrix(engine_run):
    for i in engine_run["env"]["items"]:
        acting = i["verdict"] in ("recommend", "upsize")
        assert (i["veto"] is not None) == (i["verdict"] == "reject")
        assert (i["risk"] is not None) == acting
        assert bool(i["actions"]) == acting
        assert i["trace"] and i["reason"] and i["formula"]
        if acting:
            assert i["default_option"] in i["options"]


def test_trace_rows_complete(engine_run):
    for i in engine_run["env"]["items"]:
        for t in i["trace"]:
            assert set(t) == {"step", "check", "value", "threshold", "result", "terminal"}
        assert sum(t["terminal"] for t in i["trace"]) == 1


def test_deterministic():
    cfg = Config()
    data = D.load(cfg)
    a = json.dumps(output.envelope(*PL.run(data, cfg, selection())), sort_keys=True, default=str)
    b = json.dumps(output.envelope(*PL.run(data, cfg, selection())), sort_keys=True, default=str)
    assert a == b
