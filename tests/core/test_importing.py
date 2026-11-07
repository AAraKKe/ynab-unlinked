import datetime as dt
from collections.abc import Callable
from pathlib import Path

import pytest
from ynab import TransactionClearedStatus

from tests.core.conftest import BUDGET_ID
from tests.factories import ImportRowFactory, TransactionDetailFactory, TransactionFactory
from tests.helpers.ynab_api import YnabClientStub
from ynab_unlinked.core.importing import (
    ImportPlan,
    ImportResult,
    build_import_plan,
    commit_import_plan,
    unique_files,
)
from ynab_unlinked.models import PendingImport, Transaction, assign_import_ids
from ynab_unlinked.ynab_api import Client

ACCOUNT_ID = "00000000-0000-0000-0000-00000000000a"
EXPORT = Path("export.xls")
COFFEE = TransactionFactory(date=dt.date(2025, 5, 12), payee="Coffee Shop", amount=-12.34)
BAKERY = TransactionFactory(date=dt.date(2025, 5, 14), payee="Bakery", amount=-5.0)


def ynab_holds(ynab_api: YnabClientStub, import_ids: list[str]) -> None:
    ynab_api.api("transactions").get_transactions_by_account.return_value.data.transactions = [
        TransactionDetailFactory(id=f"ynab-{i}", import_id=import_id)
        for i, import_id in enumerate(import_ids)
    ]


def ynab_rejects(ynab_api: YnabClientStub, import_ids: list[str]) -> None:
    api = ynab_api.api("transactions")
    api.create_transaction.return_value.data.duplicate_import_ids = import_ids


def plan_of(*rows) -> ImportPlan:
    return ImportPlan(entity_name="test", account_id=ACCOUNT_ID, input_file=EXPORT, rows=rows)


@pytest.mark.parametrize(
    ("export", "held_by_ynab", "expected_already_imported"),
    [
        pytest.param(
            [COFFEE, BAKERY],
            lambda pending: [pending[0].import_id],
            [True, False],
            id="by-the-ynab-import-id",
        ),
        pytest.param(
            [COFFEE, BAKERY],
            lambda pending: [pending[0].legacy_import_id],
            [True, False],
            id="by-the-id-a-previous-release-uploaded",
        ),
        pytest.param(
            [COFFEE, BAKERY],
            lambda pending: ["YNAB:-12350:2025-05-12:1", "manual-entry"],
            [False, False],
            id="an-id-one-cent-off-is-not-a-match",
        ),
        pytest.param(
            [COFFEE, COFFEE],
            lambda pending: [pending[0].import_id],
            [True, False],
            id="a-repeated-row-is-matched-occurrence-by-occurrence",
        ),
    ],
)
def test_build_import_plan_flags_the_rows_ynab_already_holds(
    client: Client,
    ynab_api: YnabClientStub,
    export: list[Transaction],
    held_by_ynab: Callable[[list[PendingImport]], list[str]],
    expected_already_imported: list[bool],
):
    ynab_holds(ynab_api, held_by_ynab(assign_import_ids(export)))

    plan = build_import_plan(client, BUDGET_ID, ACCOUNT_ID, "test", EXPORT, export)

    assert [row.already_imported for row in plan.rows] == expected_already_imported
    assert plan.already_imported_count == expected_already_imported.count(True)


@pytest.mark.parametrize(
    ("buffer", "expected_since_date"),
    [
        pytest.param({}, dt.date(2025, 4, 27), id="fifteen-days-by-default"),
        pytest.param({"buffer_days": 0}, dt.date(2025, 5, 12), id="no-buffer"),
    ],
)
def test_build_import_plan_reads_the_account_from_the_earliest_row_minus_the_buffer(
    client: Client, ynab_api: YnabClientStub, buffer: dict, expected_since_date: dt.date
):
    ynab_holds(ynab_api, [])

    build_import_plan(client, BUDGET_ID, ACCOUNT_ID, "test", EXPORT, [BAKERY, COFFEE], **buffer)

    call = ynab_api.api("transactions").get_transactions_by_account.call_args
    assert call.kwargs == {
        "plan_id": BUDGET_ID,
        "account_id": ACCOUNT_ID,
        "since_date": expected_since_date,
    }


def test_build_import_plan_of_an_empty_export_never_reaches_ynab(
    client: Client, ynab_api: YnabClientStub
):
    plan = build_import_plan(client, BUDGET_ID, ACCOUNT_ID, "test", EXPORT, [])

    assert plan.rows == ()
    ynab_api.api("transactions").get_transactions_by_account.assert_not_called()


@pytest.mark.parametrize(
    "cleared",
    [TransactionClearedStatus.CLEARED, TransactionClearedStatus.RECONCILED],
)
def test_commit_import_plan_creates_only_the_new_rows(
    client: Client, ynab_api: YnabClientStub, cleared: TransactionClearedStatus
):
    ynab_rejects(ynab_api, [])
    plan = plan_of(
        ImportRowFactory(payee="Coffee Shop", import_id="YNAB:-1:x:1", already_imported=True),
        ImportRowFactory(payee="Bakery", import_id="YNAB:-2:x:1"),
    )

    result = commit_import_plan(client, BUDGET_ID, plan, cleared)

    assert result == ImportResult(created=1, duplicate_import_ids=())
    call = ynab_api.api("transactions").create_transaction.call_args
    assert call.args[0] == BUDGET_ID
    assert [
        (str(t.account_id), t.payee_name, t.import_id, t.cleared)
        for t in call.kwargs["data"].transactions
    ] == [(ACCOUNT_ID, "Bakery", "YNAB:-2:x:1", cleared)]


def test_commit_import_plan_reports_the_rows_ynab_rejected_as_duplicates(
    client: Client, ynab_api: YnabClientStub
):
    ynab_rejects(ynab_api, ["YNAB:-1:x:1"])
    plan = plan_of(
        ImportRowFactory(payee="Coffee Shop", import_id="YNAB:-1:x:1"),
        ImportRowFactory(payee="Bakery", import_id="YNAB:-2:x:1"),
    )

    result = commit_import_plan(client, BUDGET_ID, plan, TransactionClearedStatus.CLEARED)

    assert result == ImportResult(created=1, duplicate_import_ids=("YNAB:-1:x:1",))


def test_commit_import_plan_with_nothing_new_never_reaches_ynab(
    client: Client, ynab_api: YnabClientStub
):
    plan = plan_of(ImportRowFactory(already_imported=True))

    result = commit_import_plan(client, BUDGET_ID, plan, TransactionClearedStatus.CLEARED)

    assert result == ImportResult(created=0, duplicate_import_ids=())
    ynab_api.api("transactions").create_transaction.assert_not_called()


OTHER_ACCOUNT_ID = "00000000-0000-0000-0000-00000000000b"
LUNCH = TransactionFactory(date=dt.date(2025, 5, 12), payee="Lunch", amount=-12.34)
LUNCH_ID = "YNAB:-12340:2025-05-12"


def planned(
    client: Client, account_id: str, transactions: list[Transaction], name: str
) -> ImportPlan:
    return build_import_plan(
        client,
        budget_id=BUDGET_ID,
        account_id=account_id,
        entity_name="test",
        input_file=Path(name),
        transactions=transactions,
    )


def test_an_export_overlapping_an_imported_one_finds_the_rows_they_share(
    client: Client, ynab_api: YnabClientStub
):
    # Numbered over both files, February's Lunch and Coffee were :3 and :4, created twice
    ynab_holds(ynab_api, [])
    january = planned(client, ACCOUNT_ID, [LUNCH, COFFEE], "january.xls")
    ynab_holds(ynab_api, [row.import_id for row in january.rows])

    february = planned(client, ACCOUNT_ID, [LUNCH, COFFEE, BAKERY], "february.xls")

    assert [(row.import_id, row.already_imported) for row in february.rows] == [
        (f"{LUNCH_ID}:1", True),
        (f"{LUNCH_ID}:2", True),
        ("YNAB:-5000:2025-05-14:1", False),
    ]


def test_unique_files_takes_each_export_once(tmp_path: Path):
    january, copy, february = (tmp_path / name for name in ("jan.txt", "copy.txt", "feb.txt"))
    january.write_text("01/05|LUNCH|12,34EUR")
    copy.write_text("01/05|LUNCH|12,34EUR")
    february.write_text("01/06|LUNCH|12,34EUR")

    unique, copies = unique_files([january, copy, february, january])

    assert unique == [january, february]
    assert copies == [(copy, january), (january, january)]
