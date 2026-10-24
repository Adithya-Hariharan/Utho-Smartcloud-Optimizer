"""Enforce the reasoning contract: every number is in config.yaml with a category and a why, every config
number is explained in engine/REASONING.md, and engine code contains no unexplained numeric literal."""
import ast
from pathlib import Path

import yaml

from engine.config import numeric_keys

ROOT = Path(__file__).resolve().parent.parent
CFG = yaml.safe_load((ROOT / "engine" / "config.yaml").read_text(encoding="utf-8"))
REASONING = (ROOT / "engine" / "REASONING.md").read_text(encoding="utf-8")
CATEGORIES = {"M", "C", "D", "S", "J"}
# verification code states expected values on purpose; it is not decision logic
SKIP_FILES = {"checkpoints.py", "reasoning.py"}   # verification + documentation generators, not decision logic


def test_every_config_number_has_category_and_why():
    for key in numeric_keys():
        sec, name = key.split(".", 1)
        e = CFG[sec][name]
        assert e.get("category") in CATEGORIES, key
        assert len(str(e.get("why", ""))) >= 10, key


def test_every_config_number_is_in_the_ledger():
    missing = [k for k in numeric_keys() if f"`{k}`" not in REASONING]
    assert not missing, missing


def test_presets_are_explained():
    for p in CFG["presets"]:
        assert p in REASONING


def _allowed():
    allowed = {0, 1, 100}
    allowed |= {v["value"] for v in CFG["time_units"].values()}
    return allowed


def _literals(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    skip = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "CANDIDATES" for t in node.targets):
            skip |= {id(n) for n in ast.walk(node.value)}          # candidate metadata (prior/params): documented
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in ("round", "_r"):
            skip |= {id(n) for a in node.args[1:] for n in ast.walk(a)}   # display precision, not a threshold
            skip |= {id(n) for kw in node.keywords for n in ast.walk(kw.value)}
        if isinstance(node, ast.FunctionDef):
            skip |= {id(n) for d in node.args.defaults for n in ast.walk(d)}
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            if id(node) not in skip and node.value not in _allowed():
                out.append((path.name, node.lineno, node.value))
    return out


def test_no_unexplained_numeric_literals():
    files = [p for p in (ROOT / "engine").rglob("*.py") if p.name not in SKIP_FILES]
    bad = [x for f in files for x in _literals(f)]
    assert not bad, bad
