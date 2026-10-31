from pathlib import Path

import pytest
from ynab import ApiException

from tests.factories import AccountFactory, TransactionDetailFactory, TransactionFactory
from tests.helpers import assets
from tests.helpers.types import CliRunner, LoadEntityCallback
from tests.helpers.ynab_api import YnabClientStub
from tests.process.builders import (
    ACCOUNT_ID,
    REGISTERED_ENTITY,
    THREE_DAYS_AGO,
    TODAY,
    saved_config,
    write_config,
)
from ynab_unlinked.models import assign_import_ids

pytestmark = pytest.mark.version("V3")

COFFEE = {"payee": "Coffee Shop", "amount": -12.34}


def test_yes_imports_without_asking(
    config_file: Path, yul: CliRunner, load_entity: LoadEntityCallback, created_transactions
):
    load_entity(TODAY, [TransactionFactory(date=THREE_DAYS_AGO, **COFFEE)])

    result = yul("load --yes test")

    assert result.exit_code == 0, result.output
    assert "Do you want to continue" not in result.output
    assert [t.payee_name for t in created_transactions()] == ["Coffee Shop"]


def test_yes_keeps_the_year_option_of_sabadell_working(
    config_file: Path, yul: CliRunner, ynab: YnabClientStub, created_transactions
):
    write_config(config_file, entities={"sabadell": {"account_id": ACCOUNT_ID}})

    result = yul(
        "load", "--yes", "sabadell", "-y", "2023", str(assets.path("sabadell/movements.txt"))
    )

    assert result.exit_code == 0, result.output
    assert {t.var_date.year for t in created_transactions()} == {2023}


@pytest.mark.parametrize(
    ("command", "entities", "message"),
    [
        pytest.param("load --yes test", {}, "No saved account", id="no saved account"),
        pytest.param(
            "load --yes --acount test", REGISTERED_ENTITY, "--acount", id="--yes with --acount"
        ),
        pytest.param(
            "load --yes --acount --show test", REGISTERED_ENTITY, "--acount", id="even with --show"
        ),
    ],
)
def test_yes_refuses_to_pick_an_account(
    config_file: Path,
    yul: CliRunner,
    load_entity: LoadEntityCallback,
    ynab: YnabClientStub,
    command: str,
    entities: dict,
    message: str,
):
    # A single open account must not be taken as the obvious choice
    ynab.api("accounts").get_accounts.return_value.data.accounts = [AccountFactory(id=ACCOUNT_ID)]
    write_config(config_file, entities=entities)
    load_entity(TODAY, [TransactionFactory(date=THREE_DAYS_AGO, **COFFEE)])

    result = yul(command)

    assert result.exit_code == 1, result.output
    assert message in result.output
    assert saved_config(config_file).entities.keys() == entities.keys()
    ynab.api("transactions").create_transaction.assert_not_called()


@pytest.mark.parametrize(
    "failing_call",
    [
        pytest.param("get_transactions_by_account", id="reading what is already in YNAB"),
        pytest.param("create_transaction", id="creating the transactions"),
    ],
)
def test_a_ynab_failure_is_not_reported_as_success(
    config_file: Path,
    yul: CliRunner,
    load_entity: LoadEntityCallback,
    ynab: YnabClientStub,
    failing_call: str,
):
    load_entity(TODAY, [TransactionFactory(date=THREE_DAYS_AGO, **COFFEE)])
    failing = getattr(ynab.api("transactions"), failing_call)
    failing.side_effect = ApiException(status=500, reason="Internal Server Error")

    result = yul("load --yes test")

    assert result.exit_code == 1
    assert "All done" not in result.output


def test_yes_with_everything_already_in_ynab_is_a_success(
    config_file: Path,
    yul: CliRunner,
    load_entity: LoadEntityCallback,
    ynab: YnabClientStub,
    existing_in_ynab,
):
    imported = TransactionFactory(date=THREE_DAYS_AGO, **COFFEE)
    [pending] = assign_import_ids([imported])
    existing_in_ynab([TransactionDetailFactory(import_id=pending.import_id)])
    load_entity(TODAY, [imported])

    result = yul("load --yes test")

    assert result.exit_code == 0, result.output
    assert "Nothing to do" in result.output
    ynab.api("transactions").create_transaction.assert_not_called()


def test_yes_with_rows_rejected_as_duplicates_is_a_success(
    config_file: Path,
    yul: CliRunner,
    load_entity: LoadEntityCallback,
    rejected_as_duplicates,
):
    transaction = TransactionFactory(date=THREE_DAYS_AGO, **COFFEE)
    [pending] = assign_import_ids([transaction])
    rejected_as_duplicates([pending.import_id])
    load_entity(TODAY, [transaction])

    result = yul("load --yes test")

    assert result.exit_code == 0, result.output
    assert "rejected 1" in result.output
