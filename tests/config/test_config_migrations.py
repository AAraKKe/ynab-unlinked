from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
from ynab import PlanDetail

from tests.factories import PlanDetailFactory
from tests.helpers.config import ConfigFiles
from ynab_unlinked.config import MAX_CONFIG_VERSION, Config, ConfigV1, ConfigV2, ConfigV3
from ynab_unlinked.config.core import VERSION_MAPPING
from ynab_unlinked.config.migrations.base import MigrationEngine, Version
from ynab_unlinked.config.models import DeltaConfigV1ToV2, DeltaConfigV2ToV3
from ynab_unlinked.ynab_api import Client

if TYPE_CHECKING:
    # No need to import really
    from pytest_mock import MockerFixture


@dataclass
class UnlinkMock:
    unlink: MagicMock
    rmtree: MagicMock


@pytest.fixture
def unlink(mocker: MockerFixture, config_files: ConfigFiles):
    # Ensure we are not really deleting files. The scratch directory is requested first
    # because pytest unlinks files of its own while setting it up.
    unlink_mock = mocker.patch.object(Path, "unlink")
    rmtree_mock = mocker.patch("ynab_unlinked.config.models.config_migrations.shutil.rmtree")

    yield UnlinkMock(unlink_mock, rmtree_mock)


@pytest.fixture(autouse=True)
def ynab_client_mock(mocker: MockerFixture):
    budget_patch = mocker.patch.object(Client, "budget")
    budget_patch.return_value = PlanDetailFactory()
    yield


@pytest.fixture
def load_config(config_files: ConfigFiles) -> Callable[[str], Config]:
    """
    Loads the asset of a version, putting it back on disk first.

    Every version from V2 on shares a single file, and both migrating and rolling back
    persist their result, so a version cannot be assumed to still be on disk.
    """

    def load(version: str) -> Config:
        config_files.write_asset(version)
        return VERSION_MAPPING[version].load()

    return load


def losing_what_v3_dropped(config: ConfigV1 | ConfigV2) -> ConfigV1 | ConfigV2:
    """V3 stores neither payee rules nor checkpoints, so a rollback through it cannot restore them."""
    config.payee_rules = {}
    for entity in config.entities.values():
        entity.checkpoint = None
    return config


def all_migrations_params(rollbback=False):
    result = []
    for vid in range(1, MAX_CONFIG_VERSION + 1):
        v = Version("Config", f"V{vid}")
        for wid in range(1, MAX_CONFIG_VERSION + 1):
            w = Version("Config", f"V{wid}")

            param = pytest.param(v, w, id=f"{v.version} -> {w.version}")
            if rollbback and v > w or not rollbback and v < w:
                result.append(param)
    return result


@pytest.mark.parametrize("origin, destination", all_migrations_params())
def test_migrations_on_migrate(
    origin: Version,
    destination: Version,
    unlink: UnlinkMock,
    migration_engine: MigrationEngine,
    load_config: Callable[[str], Config],
):
    destination_config = load_config(destination.version)
    origin_config = load_config(origin.version)
    destination_class = VERSION_MAPPING[destination.version]

    migrated_config = migration_engine.migrate(origin_config, destination_class)

    assert migrated_config == destination_config

    should_unlink = origin.version == "V1"
    # sourcery skip: no-conditionals-in-tests
    if should_unlink:
        unlink.rmtree.assert_called_once()


@pytest.mark.parametrize("origin, destination", all_migrations_params(True))
def test_migrations_on_rollback(
    origin: Version,
    destination: Version,
    unlink: UnlinkMock,
    migration_engine: MigrationEngine,
    load_config: Callable[[str], Config],
):
    destination_config = load_config(destination.version)
    origin_config = load_config(origin.version)
    destination_class = VERSION_MAPPING[destination.version]

    # sourcery skip: no-conditionals-in-tests
    if origin.version == "V3":
        destination_config = losing_what_v3_dropped(destination_config)  # type: ignore[arg-type]

    rolled_back_config = migration_engine.rollback(origin_config, destination_class)

    assert rolled_back_config == destination_config

    should_unlink = destination.version == "V1"
    if should_unlink:
        unlink.unlink.assert_called_once()


@pytest.mark.parametrize(
    "budget_details, expected_message",
    [
        pytest.param(
            None,
            "Could not find budget with ID",
            id="the budget stored in v1 no longer exists in ynab",
        ),
        pytest.param(
            PlanDetailFactory(currency_format=None),
            "has no currency format",
            id="the budget comes back without a currency format",
        ),
        pytest.param(
            PlanDetailFactory(date_format=None),
            "has no date format",
            id="the budget comes back without a date format",
        ),
    ],
)
def test_migration_to_v2_needs_the_full_budget_details_from_ynab(
    mocker: MockerFixture,
    budget_details: PlanDetail | None,
    expected_message: str,
    load_config: Callable[[str], Config],
):
    # V2 keeps the budget name and formats that V1 never stored, so they have to be fetched
    mocker.patch.object(Client, "budget", return_value=budget_details)
    config_v1 = load_config("V1")
    assert isinstance(config_v1, ConfigV1)

    with pytest.raises(ValueError, match=expected_message):
        DeltaConfigV1ToV2().migrate(config_v1)


def test_migration_to_v3_forgets_payee_rules_and_checkpoints(
    load_config: Callable[[str], Config],
    config_files: ConfigFiles,
):
    config_v2 = load_config("V2")
    assert isinstance(config_v2, ConfigV2)
    assert config_v2.payee_rules, "The V2 asset is expected to carry payee rules"

    config_v3 = DeltaConfigV2ToV3().migrate(config_v2)

    assert config_v3.entities.keys() == config_v2.entities.keys()

    stored = json.loads(config_files.read("V3"))
    assert "payee_rules" not in stored
    assert all(entity.keys() == {"account_id"} for entity in stored["entities"].values())


def test_rollback_from_v3_leaves_no_payee_rules_or_checkpoints(
    load_config: Callable[[str], Config],
    config_files: ConfigFiles,
):
    config_v3 = load_config("V3")
    assert isinstance(config_v3, ConfigV3)

    config_v2 = DeltaConfigV2ToV3().rollback(config_v3)

    assert config_v2.payee_rules == {}
    assert all(entity.checkpoint is None for entity in config_v2.entities.values())

    stored = json.loads(config_files.read("V2"))
    assert stored["payee_rules"] == {}
    assert stored["version"] == "V2"
