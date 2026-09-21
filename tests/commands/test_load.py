import datetime as dt

import pytest

from tests.helpers.types import CliRunner, LoadEntityCallback
from tests.helpers.ynab_api import YnabClientStub
from ynab_unlinked.commands import load

pytestmark = pytest.mark.version("V3")

# Every entity package that ships a `command` is registered as a `yul load` subcommand
SHIPPED_ENTITIES = {"bbva", "cobee", "sabadell"}


def test_load_shows_the_transactions_of_the_export(
    yul: CliRunner,
    load_entity: LoadEntityCallback,
    today: dt.datetime,
    ynab_api: YnabClientStub,
):
    load_entity(today)

    result = yul("load --show test")

    assert result.exit_code == 0, f"Error found: {result.output_bytes}"
    assert "Transactions to process" in result.output
    assert all(f"Test Payee {n}" in result.output for n in (1, 2))


def test_every_entity_package_is_registered_as_a_subcommand():
    assert {command.name for command in load.registered_commands} >= SHIPPED_ENTITIES


def test_an_unknown_entity_is_rejected(yul: CliRunner):
    result = yul("load unknown-bank")

    assert result.exit_code != 0
