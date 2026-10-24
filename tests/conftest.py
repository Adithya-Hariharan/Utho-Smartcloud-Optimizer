import json

import pytest

from engine import data as D
from engine import output
from engine import pipeline as PL
from engine.config import Config
from engine.run import selection


@pytest.fixture(scope="session")
def engine_run():
    cfg = Config()
    data = D.load(cfg)
    ctx, res = PL.run(data, cfg, selection())
    env = output.envelope(ctx, res)
    return {"cfg": cfg, "data": data, "ctx": ctx, "res": res, "env": env,
            "by_id": {i["resource"]["resource_id"]: i for i in env["items"]},
            "truth": D.load_truth()}
