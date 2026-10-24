import json  # noqa: F401  (kept from main's conftest)
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.config_loader import get_config  # noqa: E402
from backend.data_access import get_dataset  # noqa: E402
from engine import data as D  # noqa: E402
from engine import output  # noqa: E402
from engine import pipeline as PL  # noqa: E402
from engine.config import Config  # noqa: E402
from engine.run import selection  # noqa: E402


# ---- backend/ (FastAPI backend) fixtures --------------------------------------------------------

@pytest.fixture(scope="session")
def cfg():
    return get_config()


@pytest.fixture(scope="session")
def ds():
    return get_dataset()


@pytest.fixture(scope="session")
def cleaned(ds, cfg):
    from backend.pipeline.clean import clean_all
    return clean_all(ds, cfg)


@pytest.fixture(scope="session")
def features(cleaned, ds, cfg):
    from backend.pipeline.features import compute_features
    return compute_features(cleaned, ds, cfg)


@pytest.fixture(scope="session")
def name_to_id(ds):
    return dict(zip(ds.inventory["name"], ds.inventory["resource_id"]))


# ---- engine/ (checkpointed engine) fixtures -----------------------------------------------------

@pytest.fixture(scope="session")
def engine_run():
    cfg = Config()
    data = D.load(cfg)
    ctx, res = PL.run(data, cfg, selection())
    env = output.envelope(ctx, res)
    return {"cfg": cfg, "data": data, "ctx": ctx, "res": res, "env": env,
            "by_id": {i["resource"]["resource_id"]: i for i in env["items"]},
            "truth": D.load_truth()}
