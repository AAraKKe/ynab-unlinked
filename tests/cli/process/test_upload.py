import datetime as dt
from pathlib import Path

import pytest
from pytest_mock import MockerFixture
from ynab import TransactionClearedStatus

from tests.cli.process.builders import ACCOUNT_ID, BUDGET_ID, THREE_DAYS_AGO, TODAY, YESTERDAY
from tests.factories import TransactionFactory
from tests.helpers.store import upsert
from tests.helpers.types import CliRunner, LoadEntityCallback
from tests.helpers.ynab_api import YnabClientStub
from ynab_unlinked.exceptions import ParsingError
from ynab_unlinked.store import Store, StoredAccount

pytestmark = pytest.mark.version("V4")

COFFEE = {"payee": "Coffee Shop", "amount": -12.34}
BAKERY = {"payee": "Bakery", "amount": -5.0}


@pytest.mark.parametrize(
    "command",
    [
        pytest.param("load --show test", id="on its own"),
        pytest.param("load --yes --show test", id="--yes does not turn it into an import"),
    ],
)
def test_show_only_lists_the_parsed_transactions(
    config_file: Path,
    yul: CliRunner,
    load_entity: LoadEntityCallback,
    ynab: YnabClientStub,
    command: str,
):
    load_entity(
        TODAY,
        [
            TransactionFactory(date=THREE_DAYS_AGO, **COFFEE),
            TransactionFactory(date=YESTERDAY, **BAKERY),
        ],
    )

    result = yul(command)

    assert result.exit_code == 0, result.output
    assert "Coffee Shop" in result.output
    ynab.api("transactions").get_transactions_by_account.assert_not_called()
    ynab.api("transactions").create_transaction.assert_not_called()


def test_new_transactions_are_imported_with_the_payee_from_the_export(
    config_file: Path, yul: CliRunner, load_entity: LoadEntityCallback, created_transactions
):
    load_entity(
        TODAY,
        [
            TransactionFactory(date=THREE_DAYS_AGO, **COFFEE),
            TransactionFactory(date=YESTERDAY, **BAKERY),
        ],
    )

    result = yul("load test", input="y\n")

    assert result.exit_code == 0, result.output
    assert [(t.payee_name, t.amount, t.import_id) for t in created_transactions()] == [
        ("Coffee Shop", -12340, f"YNAB:-12340:{THREE_DAYS_AGO:%Y-%m-%d}:1"),
        ("Bakery", -5000, f"YNAB:-5000:{YESTERDAY:%Y-%m-%d}:1"),
    ]


def test_the_import_leaves_the_payee_for_ynab_to_resolve(
    config_file: Path, yul: CliRunner, load_entity: LoadEntityCallback, created_transactions
):
    # YNAB applies its own rename rules to an imported transaction, so sending a payee id would
    # pin the payee and defeat them
    load_entity(TODAY, [TransactionFactory(date=THREE_DAYS_AGO, payee="COMPRA EN MERCADONA 4412")])

    result = yul("load test", input="y\n")

    assert result.exit_code == 0, result.output
    [created] = created_transactions()
    assert created.payee_name == "COMPRA EN MERCADONA 4412"
    assert created.payee_id is None


@pytest.mark.parametrize(
    ("command", "expected_since_date"),
    [
        pytest.param("load test", dt.date(2025, 4, 27), id="the default buffer is fifteen days"),
        pytest.param("load -b 3 test", dt.date(2025, 5, 9), id="--buffer shortens the window"),
    ],
)
def test_ynab_is_read_from_the_earliest_transaction_minus_the_buffer(
    config_file: Path,
    yul: CliRunner,
    load_entity: LoadEntityCallback,
    ynab: YnabClientStub,
    command: str,
    expected_since_date: dt.date,
):
    load_entity(
        TODAY,
        [
            TransactionFactory(date=YESTERDAY, **BAKERY),
            TransactionFactory(date=THREE_DAYS_AGO, **COFFEE),
        ],
    )

    result = yul(command, input="n\n")

    assert result.exit_code == 0, result.output
    call = ynab.api("transactions").get_transactions_by_account.call_args
    assert call.kwargs["account_id"] == ACCOUNT_ID
    assert call.kwargs["since_date"] == expected_since_date


def test_declining_the_confirmation_uploads_nothing(
    config_file: Path, yul: CliRunner, load_entity: LoadEntityCallback, ynab: YnabClientStub
):
    load_entity(TODAY, [TransactionFactory(date=THREE_DAYS_AGO, **COFFEE)])

    result = yul("load test", input="n\n")

    assert result.exit_code == 0, result.output
    assert "Do you want to continue" in result.output
    ynab.api("transactions").create_transaction.assert_not_called()


@pytest.mark.parametrize(
    ("command", "expected_cleared"),
    [
        pytest.param("load test", TransactionClearedStatus.CLEARED, id="a plain import"),
        pytest.param(
            "load --reconcile test", TransactionClearedStatus.RECONCILED, id="--reconcile"
        ),
    ],
)
def test_the_cleared_status_the_transactions_are_imported_with(
    config_file: Path,
    yul: CliRunner,
    load_entity: LoadEntityCallback,
    created_transactions,
    command: str,
    expected_cleared: TransactionClearedStatus,
):
    load_entity(TODAY, [TransactionFactory(date=THREE_DAYS_AGO, **COFFEE)])

    result = yul(command, input="y\n")

    assert result.exit_code == 0, result.output
    assert [t.cleared for t in created_transactions()] == [expected_cleared]
    # YNAB keeps imported transactions in the unapproved inbox until the user reviews them
    assert all(not t.approved for t in created_transactions())


@pytest.mark.parametrize("command", ["load test", "load --yes test"])
def test_a_parsing_error_stops_the_load_with_an_error_code(
    config_file: Path,
    yul: CliRunner,
    load_entity: LoadEntityCallback,
    ynab: YnabClientStub,
    mocker: MockerFixture,
    command: str,
):
    load_entity(TODAY, [TransactionFactory(date=THREE_DAYS_AGO, **COFFEE)])
    mocker.patch(
        "tests.helpers.load_entity.StubEntity.parse",
        side_effect=ParsingError(input_file=Path("export.xls"), message="Column 3 is missing"),
    )

    result = yul(command)

    assert result.exit_code == 1
    assert "Column 3 is missing" in result.output


def test_an_empty_export_never_reaches_ynab(
    config_file: Path, yul: CliRunner, load_entity: LoadEntityCallback, ynab: YnabClientStub
):
    load_entity(TODAY, [])

    result = yul("load test")

    assert result.exit_code == 0, result.output
    assert "Nothing to do" in result.output
    ynab.api("transactions").get_transactions_by_account.assert_not_called()


def test_an_import_is_noted_in_the_activity_log_the_app_reads(
    config_file: Path,
    yul: CliRunner,
    load_entity: LoadEntityCallback,
    rejected_as_duplicates,
    store_file: Path,
):
    store = Store(store_file)
    upsert(
        store,
        BUDGET_ID,
        accounts=[
            StoredAccount(ACCOUNT_ID, "💶 Checking", "checking", False, True, 0, 0, 0),
        ],
    )
    load_entity(
        TODAY,
        [
            TransactionFactory(date=THREE_DAYS_AGO, **COFFEE),
            TransactionFactory(date=YESTERDAY, **BAKERY),
        ],
    )
    rejected_as_duplicates([f"YNAB:-5000:{YESTERDAY:%Y-%m-%d}:1"])

    result = yul("load test", input="y\n")

    assert result.exit_code == 0, result.output
    [entry] = store.activity(BUDGET_ID)
    assert (entry.kind, entry.message) == ("import", "Imported 1 transaction to 💶 Checking from ")
    assert entry.details == {
        "loader": "test",
        "account_id": ACCOUNT_ID,
        "account_name": "💶 Checking",
        "file": "",
        "created": 1,
        "duplicates": 1,
        "skipped": 0,
        "matched": 0,
        "excluded": 0,
    }


def test_a_store_that_cannot_be_opened_does_not_fail_the_import(
    config_file: Path,
    yul: CliRunner,
    load_entity: LoadEntityCallback,
    created_transactions,
    store_file: Path,
):
    store_file.parent.mkdir(parents=True)
    store_file.write_text("this is not a database")
    load_entity(TODAY, [TransactionFactory(date=THREE_DAYS_AGO, **COFFEE)])

    result = yul("load test", input="y\n")

    assert result.exit_code == 0, result.output
    assert len(created_transactions()) == 1
    assert "could not note it in its activity log" in result.output
    assert "1 transaction imported" in result.output
