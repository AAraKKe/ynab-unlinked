import pytest

from ynab_unlinked.config import MAX_CONFIG_VERSION, VERSION_MAPPING, Config


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
