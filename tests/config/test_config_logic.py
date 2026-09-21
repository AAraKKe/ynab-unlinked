import json

import pytest

from tests.helpers.config import ConfigFiles
from ynab_unlinked.config import Config, ConfigV3
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


@pytest.mark.version("V3")
@pytest.mark.usefixtures("config")
def test_set_entity_account_creates_an_unknown_entity():
    # The import pipeline upserts the account it just prompted for instead of registering
    # the entity first
    config_obj = ConfigV3.load()

    config_obj.set_entity_account("brand-new", "brand-new-account")

    entity = config_obj.entity("brand-new")
    assert entity is not None
    assert entity.account_id == "brand-new-account"
