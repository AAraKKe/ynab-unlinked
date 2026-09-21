from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
from ynab import PlanDetail

from tests.factories import PlanDetailFactory
from tests.helpers.config import ConfigFiles
from ynab_unlinked.config import MAX_CONFIG_VERSION
from ynab_unlinked.config.core import VERSION_MAPPING
from ynab_unlinked.config.migrations.base import MigrationEngine, Version
from ynab_unlinked.config.models import ConfigV1, DeltaConfigV1ToV2
from ynab_unlinked.ynab_api import Client

if TYPE_CHECKING:
    # No need to import really
    from pytest_mock import MockerFixture

ALL_VERSION_PARAMS = [f"V{i}" for i in range(1, MAX_CONFIG_VERSION + 1)]


@dataclass
class UnlinkMock:
    unlink: MagicMock
    rmtree: MagicMock


@pytest.fixture
def unlink(mocker: MockerFixture):
    # Ensure we are not really deleting files
    unlink_mock = mocker.patch.object(Path, "unlink")
    rmtree_mock = mocker.patch("ynab_unlinked.config.models.config_migrations.shutil.rmtree")

    yield UnlinkMock(unlink_mock, rmtree_mock)


@pytest.fixture(autouse=True)
def ynab_client_mock(mocker: MockerFixture):
    budget_patch = mocker.patch.object(Client, "budget")
    budget_patch.return_value = PlanDetailFactory()
    yield


@pytest.fixture(autouse=True)
def every_version_on_disk(config_files: ConfigFiles):
    # Migrating and rolling back both persist their result, so each version needs its own
    # scratch copy to compare against and to write to
    for version in ALL_VERSION_PARAMS:
        config_files.write_asset(version)


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
):
    origin_class = VERSION_MAPPING.get(origin.version)
    destination_class = VERSION_MAPPING.get(destination.version)

    assert origin_class is not None, f"There is no mapping for version {origin.version}"
    assert destination_class is not None, f"There is no mapping for version {origin.version}"

    origin_config = origin_class.load()
    destination_config = destination_class.load()

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
):
    origin_class = VERSION_MAPPING.get(origin.version)
    destination_class = VERSION_MAPPING.get(destination.version)

    assert origin_class is not None, f"There is no mapping for version {origin.version}"
    assert destination_class is not None, f"There is no mapping for version {origin.version}"

    origin_config = origin_class.load()
    destination_config = destination_class.load()

    migrated_config = migration_engine.rollback(origin_config, destination_class)

    assert migrated_config == destination_config

    should_unlink = origin.version == "V1"
    # sourcery skip: no-conditionals-in-tests
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
):
    # V2 keeps the budget name and formats that V1 never stored, so they have to be fetched
    mocker.patch.object(Client, "budget", return_value=budget_details)
    config_v1 = ConfigV1.load()

    with pytest.raises(ValueError, match=expected_message):
        DeltaConfigV1ToV2().migrate(config_v1)
