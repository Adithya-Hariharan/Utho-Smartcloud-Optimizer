import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.config_loader import get_config  # noqa: E402
from backend.data_access import get_dataset  # noqa: E402


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
