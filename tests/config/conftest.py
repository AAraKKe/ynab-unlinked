import pytest

from ynab_unlinked.config import MAX_CONFIG_VERSION, Config
from ynab_unlinked.config.core import VERSION_MAPPING
from ynab_unlinked.config.migrations.base import MigrationEngine
from ynab_unlinked.config.models import DeltaConfigV1ToV2


@pytest.fixture
def config_obj(config: str) -> Config:
    return VERSION_MAPPING[config].load()


def pytest_generate_tests(metafunc: pytest.Metafunc):
    # This will generate tests for each test that requires config_obj for all possible versions available of config
    if "config_obj" in metafunc.fixturenames:
        metafunc.parametrize(
            "config",
            [f"V{i}" for i in range(1, MAX_CONFIG_VERSION + 1)],
            indirect=True,
            ids=[f"ConfigV{i}" for i in range(1, MAX_CONFIG_VERSION + 1)],
        )


@pytest.fixture(scope="session")
def migration_engine() -> MigrationEngine:
    return MigrationEngine("Config", DeltaConfigV1ToV2())
