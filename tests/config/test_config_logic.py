import json
import stat
from pathlib import Path

import pytest
from pytest_mock import MockerFixture

from tests.helpers.config import ConfigFiles
from ynab_unlinked.config import Config, LatestConfig
from ynab_unlinked.config.core import VERSION_MAPPING

# This module tests the central logic of the config object. It does not focus on each particular
# version and instead ensures that the logic that needs to be supported is supported propertly

LEGACY_VERSIONS = pytest.mark.parametrize(
    "config", ["V1", "V2"], indirect=True, ids=["ConfigV1", "ConfigV2"]
)


@pytest.fixture
def stored(config: str, config_files: ConfigFiles):
    """Reads back what the config under test has on disk."""

    def read() -> dict:
        return json.loads(config_files.read(config))

    return read


def test_save(config_obj: Config, stored):
    config_obj.api_key = "some-other-api-key"  # type: ignore

    config_obj.save()

    assert stored()["api_key"] == "some-other-api-key"


@pytest.mark.parametrize(
    "name, expected_account_id",
    [
        pytest.param("sabadell", "sabadell-account", id="known_entity"),
        pytest.param("unknown", None, id="unknown_entity"),
    ],
)
def test_entity_lookup(config_obj: Config, name: str, expected_account_id: str | None):
    entity = config_obj.entity(name)
    assert (entity.account_id if entity is not None else None) == expected_account_id


def test_set_entity_account_updates_a_known_entity(config_obj: Config):
    config_obj.set_entity_account("sabadell", "another-account")

    entity = config_obj.entity("sabadell")
    assert entity is not None
    assert entity.account_id == "another-account"


@LEGACY_VERSIONS
def test_set_entity_account_ignores_an_unknown_entity_before_v3(config: str):
    config_obj = VERSION_MAPPING[config].load()

    config_obj.set_entity_account("unknown", "another-account")

    assert config_obj.entity("unknown") is None


@pytest.mark.parametrize("config", ["V3", "V4"], indirect=True, ids=["ConfigV3", "ConfigV4"])
def test_set_entity_account_creates_an_unknown_entity(config: str):
    # The import pipeline upserts the account it just prompted for instead of registering
    # the entity first
    config_obj = VERSION_MAPPING[config].load()

    config_obj.set_entity_account("brand-new", "brand-new-account")

    entity = config_obj.entity("brand-new")
    assert entity is not None
    assert entity.account_id == "brand-new-account"


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


@pytest.mark.version("missing")
def test_a_new_config_is_readable_by_the_user_only(config: str, config_files: ConfigFiles):
    config_files.write_asset("V4")
    loaded = LatestConfig.load()
    config_files.path("V4").unlink()
    config_files.path("V4").parent.rmdir()

    loaded.save()

    path = config_files.path("V4")
    assert _mode(path) == 0o600
    assert _mode(path.parent) == 0o700
    assert LatestConfig.load() == loaded


@pytest.mark.parametrize("version", ["V1", "V2", "V3"])
def test_older_versions_are_saved_readable_by_the_user_only(
    config_files: ConfigFiles, version: str
):
    # Migrations save every intermediate version, and each one holds the token in plain text
    config_class = VERSION_MAPPING[version]
    config_files.write_asset(version)
    loaded = config_class.load()
    config_files.path(version).unlink()
    config_files.path(version).parent.rmdir()

    loaded.save()

    path = config_files.path(version)
    assert (_mode(path), _mode(path.parent)) == (0o600, 0o700)
    assert config_class.load() == loaded


@pytest.mark.version("V4")
def test_saving_makes_an_existing_world_readable_config_private(
    config: str, config_files: ConfigFiles
):
    config_files.path("V4").chmod(0o644)

    LatestConfig.load().save()

    assert _mode(config_files.path("V4")) == 0o600


@pytest.mark.version("V4")
def test_a_failed_save_leaves_the_old_file_whole(
    config: str, config_files: ConfigFiles, mocker: MockerFixture
):
    before = config_files.read("V4")
    loaded = LatestConfig.load()
    loaded.set_entity_account("sabadell", "another-account")
    mocker.patch("ynab_unlinked.config.models.shared.os.replace", side_effect=OSError("disk full"))

    with pytest.raises(OSError, match="disk full"):
        loaded.save()

    assert config_files.read("V4") == before
    assert [p.name for p in config_files.path("V4").parent.iterdir()] == ["config.json"]
