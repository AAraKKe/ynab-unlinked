from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest
from ynab.models.budget_detail import BudgetDetail
from ynab.models.currency_format import CurrencyFormat
from ynab.models.date_format import DateFormat

from ynab_unlinked.config import (
    MAX_CONFIG_VERSION,
    VERSION_MAPPING,
    Version,
    migration_engine,
)
from ynab_unlinked.ynab_api import Client

if TYPE_CHECKING:
    # No need to import really
    from pytest_mock import MockerFixture

ALL_VERSION_PARAMS = [f"V{i}" for i in range(1, MAX_CONFIG_VERSION + 1)]


@pytest.fixture
def unlink(mocker: MockerFixture):
    # Ensure we are not really deleting files
    yield mocker.patch.object(Path, "unlink")


@pytest.fixture(autouse=True)
def ynab_client_mock(mocker: MockerFixture):
    budget_patch = mocker.patch.object(Client, "budget")
    budget_patch.return_value = BudgetDetail(
        id="budget_id",
        name="My Budget",
        date_format=DateFormat(format="DD/MM/YYYY"),
        currency_format=CurrencyFormat(
            iso_code="EUR",
            decimal_digits=2,
            decimal_separator=".",
            symbol_first=False,
            group_separator=",",
            currency_symbol="€",
            display_symbol=True,
            example_format="€1,234.56",
        ),
    )
    yield


@contextmanager
def mock_config_paths(origin: Version, destinoation: Version):
    # Allows mocking the versions to be returned by both config versions
    def path_and_method(v: Version):
        if v.version == "V1":
            return "ynab_unlinked.config.v1.v1_config_path"
        else:
            return f"ynab_unlinked.config.{v.version.lower()}.config_path"

    with (
        patch(path_and_method(origin)) as origin_path_patch,
        patch(path_and_method(destinoation)) as destination_path_patch,
    ):
        origin_path_patch.return_value = Path(
            f"tests/assets/config_{origin.version}/config.json"
        )
        destination_path_patch.return_value = Path(
            f"tests/assets/config_{destinoation.version}/config.json"
        )
        yield


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
    origin: Version, destination: Version, unlink: MagicMock
):
    with mock_config_paths(origin, destination):
        origin_class = VERSION_MAPPING.get(origin.version)
        destination_class = VERSION_MAPPING.get(destination.version)

        assert origin_class is not None, (
            f"There is no mapping for version {origin.version}"
        )
        assert destination_class is not None, (
            f"There is no mapping for version {origin.version}"
        )

        origin_config = origin_class.load()
        destination_config = destination_class.load()

        migrated_config = migration_engine.migrate(origin_config, destination_class)

        assert migrated_config == destination_config

        should_unlink = origin.version == "V1"
        # sourcery skip: no-conditionals-in-tests
        if should_unlink:
            unlink.assert_called_once()


@pytest.mark.parametrize("origin, destination", all_migrations_params(True))
def test_migrations_on_follback(
    origin: Version, destination: Version, unlink: MagicMock
):
    with mock_config_paths(origin, destination):
        origin_class = VERSION_MAPPING.get(origin.version)
        destination_class = VERSION_MAPPING.get(destination.version)

        assert origin_class is not None, (
            f"There is no mapping for version {origin.version}"
        )
        assert destination_class is not None, (
            f"There is no mapping for version {origin.version}"
        )

        origin_config = origin_class.load()
        destination_config = destination_class.load()

        migrated_config = migration_engine.rollback(origin_config, destination_class)

        assert migrated_config == destination_config

        should_unlink = origin.version == "V1"
        # sourcery skip: no-conditionals-in-tests
        if should_unlink:
            unlink.assert_called_once()
