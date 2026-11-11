from pathlib import Path

import pytest
from ynab import TransactionClearedStatus

from tests.cli.process.builders import ACCOUNT_ID, BUDGET_ID, THREE_DAYS_AGO, TODAY, YESTERDAY
from tests.factories import (
    StoredTransactionFactory,
    TransactionDetailFactory,
    TransactionFactory,
)
from tests.helpers.store import upsert
from tests.helpers.types import CliRunner, LoadEntityCallback
from ynab_unlinked.store import ExcludedRow, Store

pytestmark = pytest.mark.version("V4")

COFFEE = TransactionFactory(date=THREE_DAYS_AGO, payee="Coffee Shop", amount=-12.34)
BAKERY = TransactionFactory(date=YESTERDAY, payee="Bakery", amount=-5.0)
LUNCH = TransactionFactory(date=YESTERDAY, payee="Lunch", amount=-9.5)
BAKERY_ID = f"YNAB:-5000:{YESTERDAY:%Y-%m-%d}:1"
COFFEE_ID = f"YNAB:-12340:{THREE_DAYS_AGO:%Y-%m-%d}:1"


@pytest.fixture
def coffee_matched_onto_a_reconciled_one(existing_in_ynab, store_file: Path) -> None:
    """yul created the Coffee row, then the user matched it with a reconciled transaction:
    YNAB lists only that one, without the import id, and the copy keeps yul's."""
    existing_in_ynab(
        [
            TransactionDetailFactory(
                id="hand",
                var_date=THREE_DAYS_AGO,
                amount=-12340,
                cleared=TransactionClearedStatus.RECONCILED,
                matched_transaction_id="yul",
            )
        ]
    )
    upsert(
        Store(store_file),
        BUDGET_ID,
        transactions=[
            StoredTransactionFactory(
                id="yul", date=THREE_DAYS_AGO, amount=-12340, import_id=COFFEE_ID
            )
        ],
    )


@pytest.fixture
def bakery_left_out(store_file: Path) -> Store:
    store = Store(store_file)
    store.exclude(
        BUDGET_ID,
        ExcludedRow(
            account_id=ACCOUNT_ID, import_id=BAKERY_ID, date=YESTERDAY, amount=-5000, payee="Bakery"
        ),
    )
    return store


def test_a_row_matched_onto_a_reconciled_transaction_is_not_created_again(
    config_file: Path,
    yul: CliRunner,
    load_entity: LoadEntityCallback,
    coffee_matched_onto_a_reconciled_one: None,
    ynab,
):
    load_entity(TODAY, [COFFEE])

    result = yul("load test")

    assert result.exit_code == 0, result.output
    assert "matched in YNAB" in result.output
    assert "Nothing to do" in result.output
    ynab.api("transactions").create_transaction.assert_not_called()


def test_a_row_that_may_be_in_ynab_is_named_and_not_sent(
    config_file: Path,
    yul: CliRunner,
    load_entity: LoadEntityCallback,
    existing_in_ynab,
    created_transactions,
    store_file: Path,
):
    # The copy never saw the import this transaction was matched with
    existing_in_ynab(
        [
            TransactionDetailFactory(
                id="hand",
                var_date=YESTERDAY,
                amount=-12340,
                payee_name="Café",
                matched_transaction_id="unknown",
            )
        ]
    )
    load_entity(TODAY, [COFFEE, LUNCH])

    result = yul("load --yes test")

    assert result.exit_code == 0, result.output
    assert "1 row may already be in YNAB and is not sent" in result.output
    assert f"Coffee Shop -12.34€: same amount as Café on {YESTERDAY:%d/%m/%Y}" in result.output
    assert [t.payee_name for t in created_transactions()] == ["Lunch"]
    [entry] = Store(store_file).activity(BUDGET_ID)
    assert entry.details["held"] == 1


def test_a_row_matched_in_ynab_before_any_sync_is_still_recognised(
    config_file: Path,
    yul: CliRunner,
    load_entity: LoadEntityCallback,
    ynab,
    existing_in_ynab,
):
    load_entity(TODAY, [COFFEE])
    ynab.api("transactions").create_transaction.return_value.data.transactions = [
        TransactionDetailFactory(id="yul", amount=-12340, import_id=COFFEE_ID)
    ]
    assert yul("load --yes test").exit_code == 0
    # Matched with a reconciled transaction entered by hand: YNAB lists only that one
    existing_in_ynab(
        [
            TransactionDetailFactory(
                id="hand",
                var_date=THREE_DAYS_AGO,
                amount=-12340,
                cleared=TransactionClearedStatus.RECONCILED,
                matched_transaction_id="yul",
            )
        ]
    )

    result = yul("load --yes test")

    assert result.exit_code == 0, result.output
    assert "matched in YNAB" in result.output
    assert "may be in YNAB and" not in result.output
    assert ynab.api("transactions").create_transaction.call_count == 1


def test_yes_keeps_the_rows_left_out_and_notes_them_in_the_activity_log(
    config_file: Path,
    yul: CliRunner,
    load_entity: LoadEntityCallback,
    coffee_matched_onto_a_reconciled_one: None,
    bakery_left_out: Store,
    created_transactions,
):
    load_entity(TODAY, [COFFEE, BAKERY, LUNCH])

    result = yul("load --yes test")

    assert result.exit_code == 0, result.output
    assert "left out" in result.output
    assert [t.payee_name for t in created_transactions()] == ["Lunch"]
    [entry] = bakery_left_out.activity(BUDGET_ID)
    assert entry.message.endswith(" · 1 left out")
    assert (entry.details["skipped"], entry.details["matched"], entry.details["excluded"]) == (
        1,
        1,
        1,
    )


def test_a_row_left_out_in_another_account_is_imported(
    config_file: Path,
    yul: CliRunner,
    load_entity: LoadEntityCallback,
    ynab,
    store_file: Path,
    created_transactions,
):
    Store(store_file).exclude(
        BUDGET_ID,
        ExcludedRow(
            account_id="another", import_id=BAKERY_ID, date=YESTERDAY, amount=-5000, payee="Bakery"
        ),
    )
    load_entity(TODAY, [BAKERY])

    result = yul("load --yes test")

    assert result.exit_code == 0, result.output
    assert [t.payee_name for t in created_transactions()] == ["Bakery"]


@pytest.mark.parametrize(
    ("flags", "expected_exit", "expected_created"),
    [
        pytest.param("", 0, 1, id="asking-shows-the-table-and-warns"),
        pytest.param("--yes", 1, 0, id="yes-stops-rather-than-send-rows-left-out"),
    ],
)
def test_a_store_that_cannot_be_read_never_sends_unreviewed_rows(
    config_file: Path,
    yul: CliRunner,
    load_entity: LoadEntityCallback,
    ynab,
    store_file: Path,
    flags: str,
    expected_exit: int,
    expected_created: int,
):
    store_file.parent.mkdir(parents=True)
    store_file.write_text("this is not a database")
    load_entity(TODAY, [BAKERY])

    result = yul(f"load {flags} test", input="y\n")

    assert result.exit_code == expected_exit, result.output
    assert "Could not open the rows left out of imports" in result.output
    assert ynab.api("transactions").create_transaction.call_count == expected_created
