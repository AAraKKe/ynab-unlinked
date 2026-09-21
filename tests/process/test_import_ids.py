from pathlib import Path

import pytest

from tests.factories import TransactionDetailFactory, TransactionFactory
from tests.helpers.types import CliRunner, LoadEntityCallback
from tests.helpers.ynab_api import YnabClientStub
from tests.process.builders import THREE_DAYS_AGO, TODAY, YESTERDAY
from ynab_unlinked.models import assign_import_ids

pytestmark = pytest.mark.version("V3")

COFFEE = {"payee": "Coffee Shop", "amount": -12.34}
BAKERY = {"payee": "Bakery", "amount": -5.0}


def import_ids(*transactions) -> list[str]:
    return [p.import_id for p in assign_import_ids(list(transactions))]


@pytest.mark.parametrize(
    "scheme",
    [
        pytest.param("import_id", id="an id of the ynab convention"),
        pytest.param("legacy_import_id", id="an id a previous release uploaded"),
    ],
)
def test_a_transaction_ynab_already_holds_is_not_imported_again(
    config_file: Path,
    yul: CliRunner,
    load_entity: LoadEntityCallback,
    ynab: YnabClientStub,
    existing_in_ynab,
    scheme: str,
):
    imported = TransactionFactory(date=THREE_DAYS_AGO, **COFFEE)
    [pending] = assign_import_ids([imported])
    existing_in_ynab([TransactionDetailFactory(import_id=getattr(pending, scheme))])
    load_entity(TODAY, [imported])

    result = yul("load test")

    assert result.exit_code == 0, result.output
    assert "Nothing to do" in result.output
    ynab.api("transactions").create_transaction.assert_not_called()


def test_a_repeated_export_only_imports_the_rows_ynab_is_missing(
    config_file: Path,
    yul: CliRunner,
    load_entity: LoadEntityCallback,
    existing_in_ynab,
    created_transactions,
):
    already_loaded = TransactionFactory(date=THREE_DAYS_AGO, **COFFEE)
    [pending] = assign_import_ids([already_loaded])
    existing_in_ynab([TransactionDetailFactory(import_id=pending.import_id)])
    load_entity(TODAY, [already_loaded, TransactionFactory(date=YESTERDAY, **BAKERY)])

    result = yul("load test", input="y\n")

    assert result.exit_code == 0, result.output
    assert [t.payee_name for t in created_transactions()] == ["Bakery"]


def test_two_identical_rows_of_one_export_are_both_imported(
    config_file: Path, yul: CliRunner, load_entity: LoadEntityCallback, created_transactions
):
    vending = {"date": THREE_DAYS_AGO, "payee": "Vending Machine", "amount": -1.5}
    load_entity(TODAY, [TransactionFactory(**vending), TransactionFactory(**vending)])

    result = yul("load test", input="y\n")

    assert result.exit_code == 0, result.output
    assert [t.import_id for t in created_transactions()] == [
        f"YNAB:-1500:{THREE_DAYS_AGO:%Y-%m-%d}:1",
        f"YNAB:-1500:{THREE_DAYS_AGO:%Y-%m-%d}:2",
    ]


def test_the_import_ids_ynab_rejects_as_duplicates_are_reported(
    config_file: Path,
    yul: CliRunner,
    load_entity: LoadEntityCallback,
    rejected_as_duplicates,
):
    coffee = TransactionFactory(date=THREE_DAYS_AGO, **COFFEE)
    bakery = TransactionFactory(date=YESTERDAY, **BAKERY)
    rejected = import_ids(coffee, bakery)[0]
    rejected_as_duplicates([rejected])
    load_entity(TODAY, [coffee, bakery])

    result = yul("load test", input="y\n")

    assert result.exit_code == 0, result.output
    assert rejected in result.output
    assert "1 transaction imported" in result.output
