import datetime as dt
from pathlib import Path

import pytest
from pytest_mock import MockerFixture
from ynab import TransactionClearedStatus

from tests.factories import TransactionDetailFactory, TransactionFactory
from tests.helpers.types import CliRunner, LoadEntityCallback
from tests.helpers.ynab_api import YnabClientStub
from tests.process.builders import ACCOUNT_ID, BUDGET_ID, THREE_DAYS_AGO, TODAY, YESTERDAY
from ynab_unlinked.exceptions import ParsingError

pytestmark = pytest.mark.version("V2")

COFFEE = {"payee": "Coffee Shop", "amount": -12.34}
BAKERY = {"payee": "Bakery", "amount": -5.0}


def test_show_only_lists_the_parsed_transactions(
    config_file: Path, yul: CliRunner, load_entity: LoadEntityCallback, ynab: YnabClientStub
):
    load_entity(
        TODAY,
        [
            TransactionFactory(date=THREE_DAYS_AGO, **COFFEE),
            TransactionFactory(date=YESTERDAY, **BAKERY),
        ],
    )

    result = yul("load --show test")

    assert result.exit_code == 0, result.output
    assert "Coffee Shop" in result.output
    ynab.api("transactions").get_transactions_by_account.assert_not_called()


def test_unmatched_transactions_are_created_in_ynab(
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
    assert [(t.payee_name, t.amount) for t in created_transactions()] == [
        ("Coffee Shop", -12340),
        ("Bakery", -5000),
    ]


def test_transactions_already_in_ynab_are_not_created_again(
    config_file: Path,
    yul: CliRunner,
    load_entity: LoadEntityCallback,
    ynab: YnabClientStub,
    existing_in_ynab,
):
    imported = TransactionFactory(date=THREE_DAYS_AGO, **COFFEE)
    existing_in_ynab(
        [
            TransactionDetailFactory(
                var_date=THREE_DAYS_AGO,
                amount=-12340,
                payee_name="Coffee Shop",
                import_id=imported.id,
            )
        ]
    )
    load_entity(TODAY, [imported])

    result = yul("load test")

    assert result.exit_code == 0, result.output
    assert "Nothing to do" in result.output
    ynab.api("transactions").create_transaction.assert_not_called()


def test_a_repeated_import_only_uploads_what_is_missing_from_ynab(
    config_file: Path,
    yul: CliRunner,
    load_entity: LoadEntityCallback,
    existing_in_ynab,
    created_transactions,
):
    already_loaded = TransactionFactory(date=THREE_DAYS_AGO, **COFFEE)
    existing_in_ynab(
        [
            TransactionDetailFactory(
                var_date=THREE_DAYS_AGO,
                amount=-12340,
                payee_name="Coffee Shop",
                import_id=already_loaded.id,
            )
        ]
    )
    load_entity(TODAY, [already_loaded, TransactionFactory(date=YESTERDAY, **BAKERY)])

    result = yul("load test", input="y\n")

    assert result.exit_code == 0, result.output
    assert [t.payee_name for t in created_transactions()] == ["Bakery"]


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
    ynab.api("transactions").create_transaction.assert_not_called()


def test_the_payee_list_is_read_from_ynab_only_once(
    config_file: Path, yul: CliRunner, load_entity: LoadEntityCallback, ynab: YnabClientStub
):
    load_entity(
        TODAY,
        [
            TransactionFactory(date=THREE_DAYS_AGO, **COFFEE),
            TransactionFactory(date=YESTERDAY, **BAKERY),
        ],
    )

    result = yul("load test", input="n\n")

    assert result.exit_code == 0, result.output
    ynab.api("payees").get_payees.assert_called_once_with(BUDGET_ID)


@pytest.mark.parametrize(
    "already_in_ynab",
    [
        pytest.param(True, id="a transaction matched against an uncleared one"),
        pytest.param(
            False,
            id="a brand new transaction",
            marks=pytest.mark.xfail(
                reason=(
                    "--reconcile only reaches update_cleared_from_ynab, which runs on matched "
                    "transactions only (matcher.py:66), so a brand new transaction is still "
                    "uploaded as cleared despite the flag promising 'Import transactions as "
                    "reconciled instead of cleared'"
                ),
                strict=True,
            ),
        ),
    ],
)
def test_reconcile_uploads_transactions_as_reconciled(
    config_file: Path,
    yul: CliRunner,
    load_entity: LoadEntityCallback,
    existing_in_ynab,
    created_transactions,
    already_in_ynab: bool,
):
    if already_in_ynab:
        existing_in_ynab(
            [
                TransactionDetailFactory(
                    var_date=THREE_DAYS_AGO,
                    amount=-12340,
                    payee_name="Coffee Shop",
                    cleared=TransactionClearedStatus.UNCLEARED,
                )
            ]
        )
    load_entity(TODAY, [TransactionFactory(date=THREE_DAYS_AGO, **COFFEE)])

    result = yul("load --reconcile test", input="y\n")

    assert result.exit_code == 0, result.output
    assert [t.cleared for t in created_transactions()] == [TransactionClearedStatus.RECONCILED]


@pytest.mark.xfail(
    reason=(
        "preprocess_transactions numbers the duplicates on the parsed Transaction objects, but "
        "models.py:58 rebuilds them as TransactionWithYnabData, whose dataclass __post_init__ "
        "resets counter (and past) to 0. Both copies end up with the same import_id and YNAB "
        "drops the second one"
    ),
    strict=True,
)
def test_duplicated_transactions_in_the_export_are_both_uploaded(
    config_file: Path, yul: CliRunner, load_entity: LoadEntityCallback, created_transactions
):
    vending = {"date": THREE_DAYS_AGO, "payee": "Vending Machine", "amount": -1.5}
    load_entity(TODAY, [TransactionFactory(**vending), TransactionFactory(**vending)])

    result = yul("load test", input="y\n")

    assert result.exit_code == 0, result.output
    created = created_transactions()
    assert len(created) == 2
    assert created[0].import_id != created[1].import_id


def test_a_parsing_error_stops_the_load_with_an_error_code(
    config_file: Path,
    yul: CliRunner,
    load_entity: LoadEntityCallback,
    ynab: YnabClientStub,
    mocker: MockerFixture,
):
    load_entity(TODAY, [TransactionFactory(date=THREE_DAYS_AGO, **COFFEE)])
    mocker.patch(
        "tests.helpers.load_entity.StubEntity.parse",
        side_effect=ParsingError(input_file=Path("export.xls"), message="Column 3 is missing"),
    )

    result = yul("load test")

    assert result.exit_code == 1
    assert "Column 3 is missing" in result.output


@pytest.mark.xfail(
    reason=(
        "process.py:148 takes the minimum date of an empty list, so an export with no "
        "transactions dies with ValueError instead of reporting nothing to do"
    ),
    strict=True,
)
def test_an_empty_export_reports_nothing_to_do(
    config_file: Path, yul: CliRunner, load_entity: LoadEntityCallback, ynab: YnabClientStub
):
    load_entity(TODAY, [])

    result = yul("load test")

    assert result.exit_code == 0, result.output
