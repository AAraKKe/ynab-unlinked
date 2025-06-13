import pytest

from ynab_unlinked.config import LATEST_VERSION, MAX_CONFIG_VERSION
from ynab_unlinked.config.core import ConfigError, config_version
from ynab_unlinked.config.migrations.base import Version


@pytest.mark.usefixtures("config")
@pytest.mark.parametrize(
    "config, expected",
    [[f"V{i}", f"V{i}"] for i in range(1, MAX_CONFIG_VERSION + 1)] + [["V0", "V2"]],
    indirect=["config"],
    ids=[f"V{i}" for i in range(1, MAX_CONFIG_VERSION + 1)] + ["invalid_version"],
)
def test_config_verison(expected: str):
    assert config_version() == Version("Config", expected)


# The missing version does not exist in tests assets
@pytest.mark.version("missing")
@pytest.mark.usefixtures("config")
def test_config_version_with_no_file_returns_latest_version():
    assert config_version() == LATEST_VERSION


# The broken version exist but has no version in it
@pytest.mark.version("broken")
@pytest.mark.usefixtures("config")
def test_config_version_without_version_raises():
    with pytest.raises(ConfigError):
        config_version()
