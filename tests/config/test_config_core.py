from __future__ import annotations

import json

import pytest
from pytest_mock import MockerFixture

from tests.factories import PlanDetailFactory
from tests.helpers.config import ConfigFiles
from ynab_unlinked.config import ConfigV2, get_config
from ynab_unlinked.config.core import ConfigError
from ynab_unlinked.ynab_api import Client


def test_there_is_no_config_before_the_first_setup(config_files: ConfigFiles):
    assert get_config() is None


def test_a_config_from_a_newer_yul_is_reported_as_unsupported(config_files: ConfigFiles):
    config_files.write("V2", json.dumps({"version": "V9"}))

    with pytest.raises(ConfigError, match="Unsupported config version: 'Config:V9'"):
        get_config()


def test_loading_the_current_version_twice_needs_no_migration(config_files: ConfigFiles):
    # A MigrationEngine can only be registered once per class, so get_config building one
    # unconditionally would make the second call blow up.
    config_files.write_asset("V2")

    assert get_config() == get_config()


@pytest.mark.usefixtures("isolated_migration_registry")
def test_a_v1_config_is_migrated_and_replaced_by_the_current_version(
    config_files: ConfigFiles,
    mocker: MockerFixture,
):
    config_files.write_asset("V1")
    mocker.patch.object(Client, "budget", return_value=PlanDetailFactory())

    config = get_config()

    assert isinstance(config, ConfigV2)
    assert config.api_key == "my-api-key"
    assert config.budget.name == "My Budget"
    assert config.entities["sabadell"].account_id == "sabadell-account"
    assert not config_files.v1.exists(), "The migrated away V1 config was left behind"
    assert config_files.v2.is_file(), "The migration result was not persisted"
