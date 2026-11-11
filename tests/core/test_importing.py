import datetime as dt
from collections.abc import Callable
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from ynab import TransactionClearedStatus, TransactionDetail

from tests.core.conftest import BUDGET_ID
from tests.factories import (
    ImportRowFactory,
    StoredTransactionFactory,
    TransactionDetailFactory,
    TransactionFactory,
)
from tests.helpers.store import upsert
from tests.helpers.ynab_api import YnabClientStub
from ynab_unlinked.core.importing import (
    ImportPlan,
    ImportResult,
    RowStatus,
    Twin,
    build_import_plan,
    commit_import_plan,
    unique_files,
)
from ynab_unlinked.models import PendingImport, Transaction, assign_import_ids
from ynab_unlinked.store import ExcludedRow, Store
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


MAYA = TransactionFactory(date=dt.date(2025, 5, 12), payee="Maya mobile ltd", amount=-18.38)
MAYA_ID = "YNAB:-18380:2025-05-12:1"


@pytest.fixture
def store(tmp_path: Path) -> Store:
    return Store(tmp_path / "store.sqlite")


def ynab_answers(ynab_api: YnabClientStub, transactions: list) -> None:
    ynab_api.api(
        "transactions"
    ).get_transactions_by_account.return_value.data.transactions = transactions


def survivor(**fields) -> TransactionDetail:
    """The transaction entered by hand that YNAB kept when the user matched yul's with it."""
    defaults = {
        "id": "hand",
        "var_date": dt.date(2025, 5, 12),
        "amount": -18380,
        "cleared": TransactionClearedStatus.RECONCILED,
        "matched_transaction_id": "yul",
        "memo": "Maya Mobile eSIM",
    }
    return TransactionDetailFactory(**{**defaults, **fields})


def copied(store: Store, *transactions: TransactionDetail) -> None:
    """The budget copy as the delta left it: yul's transaction with its import id."""
    upsert(
        store,
        BUDGET_ID,
        transactions=[
            StoredTransactionFactory(
                id=t.id, amount=t.amount, deleted=t.deleted, import_id=t.import_id
            )
            for t in transactions
        ],
    )


YUL_MAYA = TransactionDetailFactory(
    id="yul", var_date=dt.date(2025, 5, 12), amount=-18380, import_id=MAYA_ID
)


@pytest.mark.parametrize(
    ("in_ynab", "in_copy", "expected"),
    [
        pytest.param(
            [survivor()],
            [YUL_MAYA],
            RowStatus.MATCHED,
            id="the-issue-case-a-reconciled-survivor-points-at-yuls-hidden-transaction",
        ),
        pytest.param(
            [survivor()],
            [YUL_MAYA.model_copy(update={"deleted": True})],
            RowStatus.MATCHED,
            id="the-ghost-repair-already-turned-it-into-a-tombstone",
        ),
        pytest.param(
            [survivor(import_id=MAYA_ID)],
            [],
            RowStatus.IN_YNAB,
            id="a-survivor-that-took-the-import-id-needs-no-copy",
        ),
        pytest.param(
            [survivor()],
            [YUL_MAYA.model_copy(update={"import_id": "YNAB:-18380:2025-05-12:2"})],
            RowStatus.NEW,
            id="the-transaction-it-points-at-carries-another-row-id",
        ),
        pytest.param(
            [survivor()],
            [],
            RowStatus.MAYBE_IN_YNAB,
            id="the-copy-never-saw-the-import-it-was-matched-with",
        ),
        pytest.param(
            [survivor(), YUL_MAYA],
            [],
            RowStatus.IN_YNAB,
            id="a-match-waiting-for-approval-still-lists-yuls-transaction",
        ),
        pytest.param(
            [survivor(deleted=True)],
            [YUL_MAYA],
            RowStatus.NEW,
            id="the-survivor-was-deleted",
        ),
        pytest.param(
            [survivor(matched_transaction_id=None)],
            [YUL_MAYA],
            RowStatus.NEW,
            id="a-transaction-entered-by-hand-without-a-match-is-not-enough",
        ),
    ],
)
def test_a_row_matched_in_ynab_with_a_reconciled_transaction_is_in_ynab(
    client: Client,
    ynab_api: YnabClientStub,
    store: Store,
    in_ynab: list[TransactionDetail],
    in_copy: list[TransactionDetail],
    expected: RowStatus,
):
    ynab_answers(ynab_api, in_ynab)
    copied(store, *in_copy)

    plan = build_import_plan(client, BUDGET_ID, ACCOUNT_ID, "test", EXPORT, [MAYA], store=store)

    assert [row.status for row in plan.rows] == [expected]
    assert plan.already_imported_count == (expected in (RowStatus.MATCHED, RowStatus.IN_YNAB))


def test_without_the_copy_a_match_onto_a_reconciled_transaction_is_held_back(
    client: Client, ynab_api: YnabClientStub
):
    ynab_answers(ynab_api, [survivor(payee_name="Maya Mobile")])

    plan = build_import_plan(client, BUDGET_ID, ACCOUNT_ID, "test", EXPORT, [MAYA])

    [row] = plan.rows
    assert row.status is RowStatus.MAYBE_IN_YNAB
    assert row.twin == Twin(date=dt.date(2025, 5, 12), payee="Maya Mobile")
    assert plan.new_rows == ()


def maya(day: int) -> Transaction:
    return TransactionFactory(date=dt.date(2025, 5, day), payee="Maya mobile ltd", amount=-18.38)


@pytest.mark.parametrize(
    ("export", "in_ynab", "expected"),
    [
        pytest.param(
            [maya(22)],
            [survivor()],
            [RowStatus.MAYBE_IN_YNAB],
            id="ten-days-apart-ynab-still-matches-them",
        ),
        pytest.param([maya(23)], [survivor()], [RowStatus.NEW], id="eleven-days-apart-is-too-far"),
        pytest.param(
            [maya(12)], [survivor(amount=-18390)], [RowStatus.NEW], id="one-cent-off-is-not-it"
        ),
        pytest.param(
            [maya(10), maya(13), maya(20)],
            [survivor()],
            [RowStatus.NEW, RowStatus.MAYBE_IN_YNAB, RowStatus.NEW],
            id="of-several-rows-of-the-amount-only-the-closest-in-date",
        ),
        pytest.param(
            [maya(12), maya(12)],
            [survivor()],
            [RowStatus.MAYBE_IN_YNAB, RowStatus.NEW],
            id="one-match-holds-back-one-of-two-equal-rows",
        ),
        pytest.param(
            [maya(12), maya(14)],
            [survivor(), survivor(id="hand-2", matched_transaction_id="yul-2")],
            [RowStatus.MAYBE_IN_YNAB, RowStatus.MAYBE_IN_YNAB],
            id="two-matches-hold-back-two-rows",
        ),
        pytest.param(
            [maya(12), maya(12)],
            [survivor(), TransactionDetailFactory(id="x", import_id=MAYA_ID)],
            [RowStatus.IN_YNAB, RowStatus.MAYBE_IN_YNAB],
            id="a-row-ynab-holds-leaves-the-match-to-the-other-one",
        ),
    ],
)
def test_a_match_nobody_can_name_holds_back_the_row_it_most_likely_took(
    client: Client,
    ynab_api: YnabClientStub,
    store: Store,
    export: list[Transaction],
    in_ynab: list[TransactionDetail],
    expected: list[RowStatus],
):
    ynab_answers(ynab_api, in_ynab)

    plan = build_import_plan(client, BUDGET_ID, ACCOUNT_ID, "test", EXPORT, export, store=store)

    assert [row.status for row in plan.rows] == expected


def test_a_row_that_may_be_in_ynab_is_sent_only_once_the_user_says_so(
    client: Client, ynab_api: YnabClientStub, store: Store
):
    ynab_answers(ynab_api, [survivor()])
    ynab_rejects(ynab_api, [])
    plan = build_import_plan(
        client, BUDGET_ID, ACCOUNT_ID, "test", EXPORT, [MAYA, BAKERY], store=store
    )

    commit_import_plan(client, BUDGET_ID, plan, TransactionClearedStatus.CLEARED)
    commit_import_plan(
        client, BUDGET_ID, plan.send_anyway({MAYA_ID}), TransactionClearedStatus.CLEARED
    )

    held, anyway = (
        [t.import_id for t in call.kwargs["data"].transactions]
        for call in ynab_api.api("transactions").create_transaction.call_args_list
    )
    assert held == ["YNAB:-5000:2025-05-14:1"]
    assert anyway == [MAYA_ID, "YNAB:-5000:2025-05-14:1"]


def test_a_row_that_may_be_in_ynab_can_be_left_out_and_comes_back_held(
    client: Client, ynab_api: YnabClientStub, store: Store
):
    ynab_answers(ynab_api, [survivor()])
    left_out(store, MAYA_ID)

    plan = build_import_plan(client, BUDGET_ID, ACCOUNT_ID, "test", EXPORT, [MAYA], store=store)

    assert [row.status for row in plan.rows] == [RowStatus.EXCLUDED]
    assert [row.status for row in plan.include({MAYA_ID}).rows] == [RowStatus.MAYBE_IN_YNAB]


def test_an_import_matched_before_any_sync_is_recognised_from_what_the_commit_saved(
    client: Client, ynab_api: YnabClientStub, store: Store
):
    ynab_holds(ynab_api, [])
    api = ynab_api.api("transactions")
    api.create_transaction.return_value.data.duplicate_import_ids = []
    api.create_transaction.return_value.data.transactions = [YUL_MAYA]
    plan = build_import_plan(client, BUDGET_ID, ACCOUNT_ID, "test", EXPORT, [MAYA], store=store)
    commit_import_plan(client, BUDGET_ID, plan, TransactionClearedStatus.CLEARED, store=store)
    # Matched in YNAB before a sync: YNAB hides yul's transaction from now on
    ynab_answers(ynab_api, [survivor()])

    again = build_import_plan(client, BUDGET_ID, ACCOUNT_ID, "test", EXPORT, [MAYA], store=store)

    assert [row.status for row in again.rows] == [RowStatus.MATCHED]


def test_a_copy_that_cannot_be_written_does_not_fail_an_import_ynab_took(
    client: Client, ynab_api: YnabClientStub, tmp_path: Path
):
    api = ynab_api.api("transactions")
    api.create_transaction.return_value.data.duplicate_import_ids = []
    api.create_transaction.return_value.data.transactions = [YUL_MAYA]
    store = Store(tmp_path / "store.sqlite")
    store.path.write_text("this is not a database")
    progress = MagicMock()

    result = commit_import_plan(
        client,
        BUDGET_ID,
        plan_of(ImportRowFactory(import_id=MAYA_ID)),
        TransactionClearedStatus.CLEARED,
        progress=progress,
        store=store,
    )

    assert result == ImportResult(created=1, duplicate_import_ids=())
    assert "could not be saved on this computer" in progress.warn.call_args.args[0]


def left_out(store: Store, import_id: str, account_id: str = ACCOUNT_ID) -> None:
    store.exclude(
        BUDGET_ID,
        ExcludedRow(
            account_id=account_id,
            import_id=import_id,
            date=dt.date(2025, 5, 12),
            amount=-18380,
            payee="Maya mobile ltd",
        ),
    )


def test_a_row_left_out_before_is_left_out_again(
    client: Client, ynab_api: YnabClientStub, store: Store
):
    ynab_holds(ynab_api, [])
    left_out(store, MAYA_ID)
    left_out(store, "YNAB:-5000:2025-05-14:1", account_id="another-account")

    plan = build_import_plan(
        client, BUDGET_ID, ACCOUNT_ID, "test", EXPORT, [MAYA, BAKERY], store=store
    )

    assert [row.status for row in plan.rows] == [RowStatus.EXCLUDED, RowStatus.NEW]
    assert [row.import_id for row in plan.new_rows] == ["YNAB:-5000:2025-05-14:1"]


def test_a_row_ynab_holds_stays_in_ynab_even_when_it_was_left_out(
    client: Client, ynab_api: YnabClientStub, store: Store
):
    ynab_holds(ynab_api, [MAYA_ID])
    left_out(store, MAYA_ID)

    plan = build_import_plan(client, BUDGET_ID, ACCOUNT_ID, "test", EXPORT, [MAYA], store=store)

    assert [row.status for row in plan.rows] == [RowStatus.IN_YNAB]
    assert plan.new_rows == ()


def test_a_row_included_again_is_sent_and_left_out_again_is_not(
    client: Client, ynab_api: YnabClientStub, store: Store
):
    ynab_holds(ynab_api, [])
    ynab_rejects(ynab_api, [])
    left_out(store, MAYA_ID)
    plan = build_import_plan(client, BUDGET_ID, ACCOUNT_ID, "test", EXPORT, [MAYA], store=store)

    included = plan.include({MAYA_ID})

    assert [row.status for row in included.rows] == [RowStatus.NEW]
    assert [row.status for row in included.exclude({MAYA_ID}).rows] == [RowStatus.EXCLUDED]
    commit_import_plan(client, BUDGET_ID, included, TransactionClearedStatus.CLEARED)
    sent = ynab_api.api("transactions").create_transaction.call_args.kwargs["data"].transactions
    assert [t.import_id for t in sent] == [MAYA_ID]


def test_commit_import_plan_never_sends_a_row_left_out(client: Client, ynab_api: YnabClientStub):
    plan = plan_of(
        ImportRowFactory(import_id="YNAB:-1:x:1", already_imported=True, matched=True),
        ImportRowFactory(import_id="YNAB:-2:x:1", excluded=True),
    )

    result = commit_import_plan(client, BUDGET_ID, plan, TransactionClearedStatus.CLEARED)

    assert result == ImportResult(created=0, duplicate_import_ids=())
    ynab_api.api("transactions").create_transaction.assert_not_called()
