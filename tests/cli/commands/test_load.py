import datetime as dt
import re

import pytest

from tests.helpers.types import CliRunner, LoadEntityCallback
from tests.helpers.ynab_api import YnabClientStub
from ynab_unlinked.cli.commands import load
from ynab_unlinked.entities.registry import loaders

pytestmark = pytest.mark.version("V4")

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


@pytest.mark.parametrize(
    ("key", "flag"),
    [
        pytest.param(spec.key, flag, id=f"{spec.key}{flag}")
        for spec in loaders()
        for option in spec.options
        for flag in option.cli_flags
    ],
)
def test_every_option_of_a_bank_is_an_option_of_its_command(yul: CliRunner, key: str, flag: str):
    # `yul load <bank>` is generated from the bank's spec, the one place its options live
    result = yul("load", key, "--help", env={"COLUMNS": "200"})

    assert result.exit_code == 0, result.output
    # On GitHub Actions Rich forces colour and styles `--lang` as `-` and `-lang` separately
    assert flag in re.sub(r"\x1b\[[0-9;]*m", "", result.output)


def test_an_option_that_takes_a_year_rejects_anything_else(yul: CliRunner, tmp_path):
    statement = tmp_path / "sabadell.txt"
    statement.write_text("")

    result = yul("load", "--show", "sabadell", "--year", "last", str(statement))

    assert result.exit_code == 2
