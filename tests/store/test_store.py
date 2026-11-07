import datetime as dt
import shutil
import sqlite3
import stat
import threading
import uuid
from collections.abc import Sequence
from contextlib import closing
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from freezegun import freeze_time
from ynab import (
    Account,
    AccountsResponse,
    AccountsResponseData,
    ApiException,
    TransactionClearedStatus,
    TransactionDetail,
    TransactionsResponse,
    TransactionsResponseData,
)

from tests.factories import AccountFactory, TransactionDetailFactory
from tests.helpers.ynab_api import YnabClientStub
from ynab_unlinked.core.progress import Progress
from ynab_unlinked.store import DailyAmounts, Store, StoredAccount, StoredTransaction, StoreError
from ynab_unlinked.store.migrations import SCHEMA_VERSION
from ynab_unlinked.store.store import (
    BUSY_TIMEOUT_SECONDS,
    FULL_SYNC_SINCE,
    GHOST_CHECKS_PER_SYNC,
)
from ynab_unlinked.ynab_api import Client

BUDGET_ID = "budget-1"
OTHER_BUDGET_ID = "budget-2"
CHECKING = uuid.UUID(int=1)
SAVINGS = uuid.UUID(int=2)

CLEARED = TransactionClearedStatus.CLEARED
UNCLEARED = TransactionClearedStatus.UNCLEARED
RECONCILED = TransactionClearedStatus.RECONCILED

Fetch = tuple[Sequence[TransactionDetail], int] | ApiException


@pytest.fixture
def store(tmp_path: Path) -> Store:
    return Store(tmp_path / "store.sqlite")


@pytest.fixture
def client(ynab_api: YnabClientStub) -> Client:
    """A real client whose `api` is served by the shared stub registry."""
    return Client(api_key="an-api-key")


def serve(ynab_api: YnabClientStub, *fetches: Fetch, accounts: Sequence[Account] = ()) -> None:
    """Answer each get_transactions call with the next fetch, and every accounts call alike."""
    ynab_api.api("transactions").get_transactions.side_effect = [
        fetch
        if isinstance(fetch, ApiException)
        else TransactionsResponse(
            data=TransactionsResponseData(transactions=list(fetch[0]), server_knowledge=fetch[1])
        )
        for fetch in fetches
    ]
    ynab_api.api("accounts").get_accounts.return_value = AccountsResponse(
        data=AccountsResponseData(accounts=list(accounts), server_knowledge=1)
    )


def transactions_calls(ynab_api: YnabClientStub) -> list[dict]:
    return [c.kwargs for c in ynab_api.api("transactions").get_transactions.call_args_list]


def ids(transactions: Sequence[StoredTransaction]) -> list[str]:
    return [t.id for t in transactions]


def test_opening_creates_the_schema_and_its_directory(tmp_path: Path):
    path = tmp_path / "nested" / "store.sqlite"

    Store(path)

    with closing(sqlite3.connect(path)) as conn:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master")}
    assert version == SCHEMA_VERSION
    assert {"accounts", "transactions", "sync_state", "activity"} <= tables


def test_the_store_and_its_directory_are_for_the_user_only(tmp_path: Path):
    path = tmp_path / "nested" / "store.sqlite"

    Store(path)
    path.chmod(0o644)  # one written by 1.0.0
    path.parent.chmod(0o755)
    Store(path)

    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700


def test_a_store_whose_file_was_deleted_serves_queries_again(tmp_path: Path):
    # `yul config reset` deletes the file while the app keeps its open store
    path = tmp_path / "data" / "store.sqlite"
    store = Store(path)
    store.log(BUDGET_ID, "sync", "before the reset")
    shutil.rmtree(path.parent)

    assert store.accounts(BUDGET_ID) == []
    store.log(BUDGET_ID, "import", "after the reset")

    assert [a.message for a in store.activity(BUDGET_ID)] == ["after the reset"]
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_two_stores_on_one_file_read_while_the_other_writes(tmp_path: Path):
    path = tmp_path / "store.sqlite"
    app, cli = Store(path), Store(path)
    app.log(BUDGET_ID, "sync", "before")

    with closing(sqlite3.connect(path)) as writer:
        writer.execute("BEGIN EXCLUSIVE")
        writer.execute(
            "INSERT INTO activity (budget_id, at, kind, message, details) "
            "VALUES (?, '2025-01-01', 'import', 'pending', '{}')",
            (BUDGET_ID,),
        )
        # Without WAL this read waits for the exclusive lock and fails
        seen = [a.message for a in cli.activity(BUDGET_ID)]
        writer.rollback()

    assert seen == ["before"]


def test_a_write_waits_for_the_other_writer_instead_of_failing(tmp_path: Path):
    path = tmp_path / "store.sqlite"
    app, cli = Store(path), Store(path)
    release = threading.Event()

    def hold_the_lock() -> None:
        with closing(sqlite3.connect(path)) as writer:
            writer.execute("BEGIN IMMEDIATE")
            release.wait()
            writer.rollback()

    holder = threading.Thread(target=hold_the_lock)
    holder.start()
    threading.Timer(0.3, release.set).start()
    cli.log(BUDGET_ID, "import", "from the CLI")
    holder.join()

    assert [a.message for a in app.activity(BUDGET_ID)] == ["from the CLI"]
    assert BUSY_TIMEOUT_SECONDS == 30


def test_the_store_uses_write_ahead_logging(tmp_path: Path):
    path = tmp_path / "store.sqlite"

    Store(path)

    with closing(sqlite3.connect(path)) as conn:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"


def test_reopening_keeps_what_was_stored(tmp_path: Path):
    path = tmp_path / "store.sqlite"
    Store(path).log(BUDGET_ID, "import", "Imported 3 transactions")

    assert [a.message for a in Store(path).activity(BUDGET_ID)] == ["Imported 3 transactions"]


def test_opening_a_store_from_a_newer_yul_fails(tmp_path: Path):
    path = tmp_path / "store.sqlite"
    Store(path)
    with closing(sqlite3.connect(path)) as conn:
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 1}")

    with pytest.raises(StoreError, match="newer version of yul"):
        Store(path)


def test_sync_stores_every_field_the_app_reads(store: Store, client: Client, ynab_api):
    transfer = TransactionDetailFactory(
        id="t1",
        account_id=CHECKING,
        var_date=dt.date(2025, 5, 1),
        amount=-250000,
        cleared=UNCLEARED,
        approved=False,
        payee_name="Transfer : Savings",
        category_name=None,
        import_id="YNAB:-250000:2025-05-01:1",
        memo="Monthly saving",
        transfer_account_id=SAVINGS,
    )
    serve(ynab_api, ([transfer], 10))

    store.sync(client, BUDGET_ID)

    assert store.transactions(BUDGET_ID) == [
        StoredTransaction(
            id="t1",
            account_id=str(CHECKING),
            date=dt.date(2025, 5, 1),
            amount=-250000,
            cleared=UNCLEARED,
            approved=False,
            deleted=False,
            payee_name="Transfer : Savings",
            category_name=None,
            import_id="YNAB:-250000:2025-05-01:1",
            memo="Monthly saving",
            transfer_account_id=str(SAVINGS),
        )
    ]


def test_full_sync_then_delta_sync_applies_changes_and_deletions(
    store: Store, client: Client, ynab_api: YnabClientStub
):
    serve(
        ynab_api,
        (
            [
                TransactionDetailFactory(id="t1", amount=-10000),
                TransactionDetailFactory(id="t2", amount=-20000),
            ],
            10,
        ),
        (
            [
                TransactionDetailFactory(id="t1", amount=-12000),
                TransactionDetailFactory(id="t2", amount=-20000, deleted=True),
                TransactionDetailFactory(id="t3", amount=-30000),
            ],
            15,
        ),
    )

    first = store.sync(client, BUDGET_ID)
    second = store.sync(client, BUDGET_ID)

    assert (first.full, first.transactions_changed, first.server_knowledge) == (True, 2, 10)
    assert (second.full, second.transactions_changed, second.server_knowledge) == (False, 3, 15)
    assert transactions_calls(ynab_api) == [
        {"plan_id": BUDGET_ID, "since_date": FULL_SYNC_SINCE},
        {"plan_id": BUDGET_ID, "last_knowledge_of_server": 10},
    ]
    assert {t.id: t.amount for t in store.transactions(BUDGET_ID)} == {
        "t1": -12000,
        "t3": -30000,
    }


MERGED_IMPORT_ID = "YNAB:-12900:2026-11-01:1"


def answer_exists(ynab_api: YnabClientStub, missing: set[str]) -> MagicMock:
    """Make get_transaction_by_id answer 404 for the `missing` ids and return the mock."""

    def get_transaction_by_id(plan_id: str, transaction_id: str) -> MagicMock:
        if transaction_id in missing:
            raise ApiException(status=404, reason="Not Found")
        return MagicMock()

    endpoint = ynab_api.api("transactions").get_transaction_by_id
    endpoint.side_effect = get_transaction_by_id
    return endpoint


def test_sync_tombstones_the_import_ynab_merged_into_a_manual_transaction(
    store: Store, client: Client, ynab_api: YnabClientStub
):
    # YNAB merged the import into the manual one, which took its import id; the imported id
    # is gone (404) but no delta ever reports it as deleted
    serve(
        ynab_api,
        ([TransactionDetailFactory(id="imported", import_id=MERGED_IMPORT_ID)], 10),
        ([TransactionDetailFactory(id="manual", import_id=MERGED_IMPORT_ID)], 15),
    )
    endpoint = answer_exists(ynab_api, missing={"imported"})
    first = store.sync(client, BUDGET_ID)

    second = store.sync(client, BUDGET_ID)

    assert (first.ghosts_removed, second.ghosts_removed) == (0, 1)
    assert ids(store.unreconciled(BUDGET_ID)) == ["manual"]
    assert sorted(c.kwargs["transaction_id"] for c in endpoint.call_args_list) == [
        "imported",
        "manual",
    ]


def test_sync_without_duplicate_import_ids_makes_no_extra_request(
    store: Store, client: Client, ynab_api: YnabClientStub
):
    rows = [
        TransactionDetailFactory(id="t1", import_id=MERGED_IMPORT_ID),
        TransactionDetailFactory(id="t2", import_id="YNAB:-5000:2026-11-01:1"),
        # Same import id in another account, a deleted row and rows without import id
        TransactionDetailFactory(id="t3", import_id=MERGED_IMPORT_ID, account_id=SAVINGS),
        TransactionDetailFactory(id="t4", import_id=MERGED_IMPORT_ID, deleted=True),
        TransactionDetailFactory(id="t5"),
        TransactionDetailFactory(id="t6"),
    ]
    serve(ynab_api, (rows, 10))
    endpoint = answer_exists(ynab_api, missing=set())

    result = store.sync(client, BUDGET_ID)

    assert result.ghosts_removed == 0
    endpoint.assert_not_called()


def test_sync_keeps_a_match_ynab_has_not_merged_yet(
    store: Store, client: Client, ynab_api: YnabClientStub
):
    serve(
        ynab_api,
        (
            [
                TransactionDetailFactory(id="imported", import_id=MERGED_IMPORT_ID),
                TransactionDetailFactory(id="manual", import_id=MERGED_IMPORT_ID),
            ],
            10,
        ),
    )
    answer_exists(ynab_api, missing=set())

    result = store.sync(client, BUDGET_ID)

    assert result.ghosts_removed == 0
    assert ids(store.unreconciled(BUDGET_ID)) == ["imported", "manual"]


def test_a_pending_match_is_only_checked_by_the_sync_that_brings_it(
    store: Store, client: Client, ynab_api: YnabClientStub
):
    pending = [
        TransactionDetailFactory(id="imported", import_id=MERGED_IMPORT_ID),
        TransactionDetailFactory(id="manual", import_id=MERGED_IMPORT_ID),
    ]
    serve(
        ynab_api,
        (pending, 10),
        # Later deltas bring other rows, or the manual one after the user approved the match
        ([TransactionDetailFactory(id="other")], 15),
        ([], 16),
        ([TransactionDetailFactory(id="manual", import_id=MERGED_IMPORT_ID)], 20),
    )
    endpoint = answer_exists(ynab_api, missing=set())

    store.sync(client, BUDGET_ID)
    assert endpoint.call_count == 2
    store.sync(client, BUDGET_ID)
    store.sync(client, BUDGET_ID)
    assert endpoint.call_count == 2

    endpoint.side_effect = None
    answer_exists(ynab_api, missing={"imported"})
    result = store.sync(client, BUDGET_ID)

    assert result.ghosts_removed == 1
    assert ids(store.unreconciled(BUDGET_ID)) == ["manual", "other"]


def test_a_full_sync_checks_every_duplicate_group(
    store: Store, client: Client, ynab_api: YnabClientStub
):
    serve(
        ynab_api,
        (
            [
                TransactionDetailFactory(id="imported", import_id=MERGED_IMPORT_ID),
                TransactionDetailFactory(id="manual", import_id=MERGED_IMPORT_ID),
            ],
            10,
        ),
    )
    answer_exists(ynab_api, missing={"imported"})

    result = store.sync(client, BUDGET_ID)

    assert (result.full, result.ghosts_removed) == (True, 1)


def merged_groups(count: int) -> list[TransactionDetail]:
    """`count` merges: an `imported-<n>` gone from YNAB and the `manual-<n>` that took its id."""
    return [
        TransactionDetailFactory(id=f"{kind}-{n:02d}", import_id=f"YNAB:-{n + 1}000:2026-11-01:1")
        for n in range(count)
        for kind in ("imported", "manual")
    ]


def test_a_sync_checks_a_limited_number_and_leaves_the_rest_for_the_next(
    store: Store, client: Client, ynab_api: YnabClientStub
):
    # 30 groups of two: 60 ids, more than one sync checks
    serve(ynab_api, (merged_groups(30), 10), ([], 15), ([], 16))
    endpoint = answer_exists(ynab_api, missing={f"imported-{n:02d}" for n in range(30)})
    progress = MagicMock(spec=Progress)

    first = store.sync(client, BUDGET_ID, progress)
    first_calls = endpoint.call_count
    second = store.sync(client, BUDGET_ID)
    third = store.sync(client, BUDGET_ID)

    assert first_calls == GHOST_CHECKS_PER_SYNC == 50
    assert (first.ghosts_removed, second.ghosts_removed, third.ghosts_removed) == (25, 5, 0)
    assert endpoint.call_count == 60
    progress.warn.assert_called_once()
    assert "10 more transactions" in progress.warn.call_args.args[0]
    assert ids(store.unreconciled(BUDGET_ID)) == [f"manual-{n:02d}" for n in range(30)]


def test_a_failed_ghost_check_is_tried_again_on_the_next_sync(
    store: Store, client: Client, ynab_api: YnabClientStub
):
    serve(ynab_api, (merged_groups(1), 10), ([], 15))
    endpoint = ynab_api.api("transactions").get_transaction_by_id
    endpoint.side_effect = ApiException(status=429, reason="Too Many Requests")
    store.sync(client, BUDGET_ID)

    endpoint.side_effect = None
    answer_exists(ynab_api, missing={"imported-00"})
    result = store.sync(client, BUDGET_ID)

    assert result.ghosts_removed == 1
    assert ids(store.unreconciled(BUDGET_ID)) == ["manual-00"]


@pytest.mark.parametrize(
    "error",
    [ApiException(status=429, reason="Too Many Requests"), ConnectionRefusedError("offline")],
    ids=["rate-limited", "offline"],
)
def test_a_failed_ghost_check_warns_and_keeps_the_sync(
    store: Store, client: Client, ynab_api: YnabClientStub, error: Exception
):
    serve(
        ynab_api,
        (
            [
                TransactionDetailFactory(id="imported", import_id=MERGED_IMPORT_ID),
                TransactionDetailFactory(id="manual", import_id=MERGED_IMPORT_ID),
            ],
            10,
        ),
    )
    ynab_api.api("transactions").get_transaction_by_id.side_effect = error
    progress = MagicMock(spec=Progress)

    result = store.sync(client, BUDGET_ID, progress)

    assert (result.server_knowledge, result.ghosts_removed) == (10, 0)
    assert ids(store.unreconciled(BUDGET_ID)) == ["imported", "manual"]
    assert store.last_sync(BUDGET_ID) is not None
    progress.warn.assert_called_once()


def test_stale_knowledge_drops_the_budget_and_fetches_everything_again(
    store: Store, client: Client, ynab_api: YnabClientStub
):
    serve(
        ynab_api,
        ([TransactionDetailFactory(id="t1"), TransactionDetailFactory(id="t2")], 10),
        ApiException(status=409, reason="Conflict"),
        ([TransactionDetailFactory(id="t3")], 20),
    )
    progress = MagicMock(spec=Progress)
    store.sync(client, BUDGET_ID)

    result = store.sync(client, BUDGET_ID, progress)

    assert (result.full, result.server_knowledge) == (True, 20)
    assert transactions_calls(ynab_api)[1:] == [
        {"plan_id": BUDGET_ID, "last_knowledge_of_server": 10},
        {"plan_id": BUDGET_ID, "since_date": FULL_SYNC_SINCE},
    ]
    # t1 and t2 were not in the new full fetch, so they no longer exist in YNAB
    assert ids(store.transactions(BUDGET_ID)) == ["t3"]
    progress.warn.assert_called_once()


@pytest.mark.parametrize(
    ("fetches", "kept"),
    [
        pytest.param(
            [([TransactionDetailFactory(id="t1")], 10), ApiException(status=500)],
            ["t1"],
            id="a server error on a delta keeps the stored rows",
        ),
        pytest.param(
            [ApiException(status=409)],
            [],
            id="a conflict on a full fetch is not retried",
        ),
    ],
)
def test_sync_errors_other_than_stale_knowledge_propagate(
    store: Store,
    client: Client,
    ynab_api: YnabClientStub,
    fetches: list[Fetch],
    kept: list[str],
):
    serve(ynab_api, *fetches)
    for _ in fetches[:-1]:
        store.sync(client, BUDGET_ID)

    with pytest.raises(ApiException):
        store.sync(client, BUDGET_ID)

    assert len(transactions_calls(ynab_api)) == len(fetches)
    assert ids(store.transactions(BUDGET_ID)) == kept


def test_sync_refreshes_accounts_keeping_closed_ones_and_skipping_deleted(
    store: Store, client: Client, ynab_api: YnabClientStub
):
    serve(
        ynab_api,
        ([], 1),
        ([], 2),
        accounts=[
            AccountFactory(id=CHECKING, name="Checking", balance=1000),
            AccountFactory(id=SAVINGS, name="Old savings", type="savings", closed=True),
            AccountFactory(id=uuid.UUID(int=3), name="Removed", deleted=True),
        ],
    )
    store.sync(client, BUDGET_ID)
    first = store.accounts(BUDGET_ID)
    ynab_api.api("accounts").get_accounts.return_value = AccountsResponse(
        data=AccountsResponseData(
            accounts=[AccountFactory(id=CHECKING, name="Checking", balance=5000)],
            server_knowledge=2,
        )
    )

    result = store.sync(client, BUDGET_ID)

    assert first == [
        StoredAccount(
            id=str(CHECKING),
            name="Checking",
            type="checking",
            closed=False,
            on_budget=True,
            balance=1000,
            cleared_balance=0,
            uncleared_balance=0,
        ),
        StoredAccount(
            id=str(SAVINGS),
            name="Old savings",
            type="savings",
            closed=True,
            on_budget=True,
            balance=0,
            cleared_balance=0,
            uncleared_balance=0,
        ),
    ]
    assert result.accounts == 1
    assert [(a.name, a.balance) for a in store.accounts(BUDGET_ID)] == [("Checking", 5000)]


@pytest.fixture
def synced(store: Store, client: Client, ynab_api: YnabClientStub) -> Store:
    serve(
        ynab_api,
        (
            [
                TransactionDetailFactory(id="t1", var_date=dt.date(2025, 5, 1), cleared=CLEARED),
                TransactionDetailFactory(id="t2", var_date=dt.date(2025, 5, 10), cleared=UNCLEARED),
                TransactionDetailFactory(
                    id="t3", var_date=dt.date(2025, 5, 15), cleared=RECONCILED
                ),
                TransactionDetailFactory(
                    id="t4", account_id=SAVINGS, var_date=dt.date(2025, 5, 10), cleared=CLEARED
                ),
                TransactionDetailFactory(
                    id="t5", var_date=dt.date(2025, 5, 12), cleared=UNCLEARED, deleted=True
                ),
            ],
            10,
        ),
    )
    store.sync(client, BUDGET_ID)
    return store


@pytest.mark.parametrize(
    ("filters", "expected"),
    [
        pytest.param({}, ["t1", "t2", "t4", "t3"], id="everything oldest first"),
        pytest.param({"account_id": str(CHECKING)}, ["t1", "t2", "t3"], id="one account"),
        pytest.param({"since": dt.date(2025, 5, 10)}, ["t2", "t4", "t3"], id="since inclusive"),
        pytest.param({"until": dt.date(2025, 5, 10)}, ["t1", "t2", "t4"], id="until inclusive"),
        pytest.param(
            {"since": dt.date(2025, 5, 10), "until": dt.date(2025, 5, 10)},
            ["t2", "t4"],
            id="a single day",
        ),
        pytest.param({"cleared": [RECONCILED]}, ["t3"], id="one cleared status"),
        pytest.param({"cleared": []}, [], id="no cleared status matches nothing"),
        pytest.param(
            {"account_id": str(SAVINGS), "cleared": [CLEARED, UNCLEARED]},
            ["t4"],
            id="filters combine",
        ),
        pytest.param({"account_id": "unknown"}, [], id="unknown account"),
    ],
)
def test_transactions_filters_never_return_deleted_rows(
    synced: Store, filters: dict, expected: list[str]
):
    assert ids(synced.transactions(BUDGET_ID, **filters)) == expected


def test_transactions_are_scoped_to_the_budget(synced: Store):
    assert synced.transactions(OTHER_BUDGET_ID) == []


def test_unreconciled_lists_cleared_and_uncleared_across_accounts(synced: Store):
    assert ids(synced.unreconciled(BUDGET_ID)) == ["t1", "t2", "t4"]


def test_daily_amounts_sum_each_day_per_account_within_the_budget(
    store: Store, client: Client, ynab_api: YnabClientStub
):
    may = {n: dt.date(2025, 5, n) for n in (1, 2, 3)}
    serve(
        ynab_api,
        (
            [
                TransactionDetailFactory(id="t1", var_date=may[1], amount=-10_000),
                TransactionDetailFactory(id="t2", var_date=may[1], amount=-5_000),
                TransactionDetailFactory(id="t3", var_date=may[2], amount=70_000, deleted=True),
                TransactionDetailFactory(id="t4", var_date=may[3], amount=2_000),
                TransactionDetailFactory(
                    id="t5", account_id=SAVINGS, var_date=may[2], amount=3_000
                ),
            ],
            10,
        ),
        ([TransactionDetailFactory(id="other", var_date=may[1], amount=-1_000_000)], 20),
        accounts=[AccountFactory(id=CHECKING, balance=987_000)],
    )
    store.sync(client, BUDGET_ID)
    store.sync(client, OTHER_BUDGET_ID)

    checking = DailyAmounts(balance=987_000, days=((may[1], -15_000), (may[3], 2_000)))
    # Savings has transactions but no account row, like an account deleted in YNAB
    savings = DailyAmounts(balance=None, days=((may[2], 3_000),))
    assert store.daily_amounts(BUDGET_ID) == {str(CHECKING): checking, str(SAVINGS): savings}
    assert store.daily_amounts(BUDGET_ID, [str(SAVINGS), "unknown"]) == {str(SAVINGS): savings}
    assert store.daily_amounts(BUDGET_ID, []) == {}


def test_last_sync_is_the_time_of_the_latest_sync_in_utc(
    store: Store, client: Client, ynab_api: YnabClientStub
):
    serve(ynab_api, ([], 1), ([], 2))
    assert store.last_sync(BUDGET_ID) is None

    with freeze_time("2025-05-15 10:00:00"):
        store.sync(client, BUDGET_ID)
    with freeze_time("2025-05-16 08:30:00"):
        store.sync(client, BUDGET_ID)

    assert store.last_sync(BUDGET_ID) == dt.datetime(2025, 5, 16, 8, 30, tzinfo=dt.UTC)
    assert store.last_sync(OTHER_BUDGET_ID) is None


def test_a_write_logged_while_the_sync_fetches_counts_as_newer_than_the_sync(
    store: Store, client: Client, ynab_api: YnabClientStub
):
    def cli_imports_meanwhile(*args: object, **kwargs: object) -> TransactionsResponse:
        # `yul load` in a terminal while the app waits for YNAB
        store.log(BUDGET_ID, "import", "Imported 1 transaction")
        return TransactionsResponse(
            data=TransactionsResponseData(transactions=[], server_knowledge=1)
        )

    serve(ynab_api)
    ynab_api.api("transactions").get_transactions.side_effect = cli_imports_meanwhile

    store.sync(client, BUDGET_ID)

    synced, written = store.last_sync(BUDGET_ID), store.last_activity(BUDGET_ID)
    assert synced is not None and written is not None and synced < written


def test_an_older_delta_written_last_never_takes_the_knowledge_back(
    store: Store, client: Client, ynab_api: YnabClientStub
):
    # Another run of the app already wrote knowledge 30 when this delta, at 20, lands
    serve(ynab_api, ([], 30), ([], 20), ([], 31))
    store.sync(client, BUDGET_ID)
    store.sync(client, BUDGET_ID)

    store.sync(client, BUDGET_ID)

    assert [c.get("last_knowledge_of_server") for c in transactions_calls(ynab_api)] == [
        None,
        30,
        30,
    ]


def test_clearing_a_budget_leaves_the_others_and_forces_a_full_sync(
    store: Store, client: Client, ynab_api: YnabClientStub
):
    serve(
        ynab_api,
        ([TransactionDetailFactory(id="t1")], 10),
        ([TransactionDetailFactory(id="t2")], 20),
        ([TransactionDetailFactory(id="t3")], 30),
        accounts=[AccountFactory()],
    )
    store.sync(client, BUDGET_ID)
    store.sync(client, OTHER_BUDGET_ID)
    store.log(BUDGET_ID, "import", "Imported")
    store.log(OTHER_BUDGET_ID, "import", "Imported")

    store.clear(BUDGET_ID)

    assert store.transactions(BUDGET_ID) == []
    assert store.accounts(BUDGET_ID) == []
    assert store.last_sync(BUDGET_ID) is None
    # What yul did is not a copy of YNAB: it stays
    assert len(store.activity(BUDGET_ID)) == 1
    assert ids(store.transactions(OTHER_BUDGET_ID)) == ["t2"]
    assert len(store.accounts(OTHER_BUDGET_ID)) == 1
    assert len(store.activity(OTHER_BUDGET_ID)) == 1

    assert store.sync(client, BUDGET_ID).full


def test_clearing_a_budget_with_its_activity_drops_its_log_only(synced: Store):
    synced.log(BUDGET_ID, "sync", "Synced")
    synced.log(OTHER_BUDGET_ID, "sync", "Synced")

    synced.clear(BUDGET_ID, activity=True)

    assert synced.activity(BUDGET_ID) == []
    assert len(synced.activity(OTHER_BUDGET_ID)) == 1


def test_clearing_everything_empties_every_budget(synced: Store):
    synced.log(BUDGET_ID, "sync", "Synced")
    synced.log(OTHER_BUDGET_ID, "sync", "Synced")

    synced.clear(activity=True)

    assert synced.transactions(BUDGET_ID) == []
    assert synced.last_sync(BUDGET_ID) is None
    assert synced.activity(BUDGET_ID) == []
    assert synced.activity(OTHER_BUDGET_ID) == []


def test_activity_is_newest_first_limited_and_per_budget(store: Store):
    with freeze_time("2025-05-15 10:00:00") as frozen:
        store.log(BUDGET_ID, "import", "first", {"count": 3})
        # Logged in the same instant: insertion order breaks the tie
        store.log(BUDGET_ID, "reconcile", "second")
        frozen.tick(dt.timedelta(minutes=5))
        store.log(BUDGET_ID, "adjustment", "third")
        store.log(OTHER_BUDGET_ID, "sync", "elsewhere")

    everything = store.activity(BUDGET_ID)
    latest = store.activity(BUDGET_ID, limit=2)

    assert [(a.kind, a.message) for a in everything] == [
        ("adjustment", "third"),
        ("reconcile", "second"),
        ("import", "first"),
    ]
    assert [a.message for a in latest] == ["third", "second"]
    assert everything[0].at == dt.datetime(2025, 5, 15, 10, 5, tzinfo=dt.UTC)
    assert everything[1].details == {}
    assert everything[2].details == {"count": 3}


def test_activity_filters_by_kind_and_orders_backdated_entries_by_time(store: Store):
    madrid = dt.timezone(dt.timedelta(hours=2))
    store.log(BUDGET_ID, "import", "recent", {"loader": "sabadell"})
    # 23:30 in Madrid on the 1st is 21:30 UTC, so it sorts before 22:00 UTC
    store.log(BUDGET_ID, "import", "older", at=dt.datetime(2025, 5, 1, 23, 30, tzinfo=madrid))
    store.log(BUDGET_ID, "import", "oldest", at=dt.datetime(2025, 5, 1, 22, 0, tzinfo=dt.UTC))
    store.log(BUDGET_ID, "sync", "not an import")

    imports = store.activity(BUDGET_ID, limit=None, kind="import")

    assert [a.message for a in imports] == ["recent", "oldest", "older"]
    assert imports[2].at == dt.datetime(2025, 5, 1, 21, 30, tzinfo=dt.UTC)
    assert [a.message for a in store.activity(BUDGET_ID, limit=1, kind="sync")] == ["not an import"]


def test_last_activity_is_the_newest_entry_of_the_budget_leaving_out_a_kind(store: Store):
    assert store.last_activity(BUDGET_ID) is None
    store.log(BUDGET_ID, "import", "a file", at=dt.datetime(2025, 5, 1, 10, tzinfo=dt.UTC))
    store.log(BUDGET_ID, "sync", "a sync", at=dt.datetime(2025, 5, 2, 10, tzinfo=dt.UTC))
    store.log(OTHER_BUDGET_ID, "import", "elsewhere", at=dt.datetime(2025, 5, 3, tzinfo=dt.UTC))

    assert store.last_activity(BUDGET_ID) == dt.datetime(2025, 5, 2, 10, tzinfo=dt.UTC)
    assert store.last_activity(BUDGET_ID, other_than="sync") == dt.datetime(
        2025, 5, 1, 10, tzinfo=dt.UTC
    )


def test_last_import_per_loader_is_the_newest_import_of_each_bank_in_the_budget(store: Store):
    def at(day: int, hour: int = 10) -> dt.datetime:
        return dt.datetime(2025, 5, day, hour, tzinfo=dt.UTC)

    madrid = dt.timezone(dt.timedelta(hours=2))
    store.log(BUDGET_ID, "import", "newest", {"loader": "sabadell"}, at=at(3))
    store.log(BUDGET_ID, "import", "older", {"loader": "sabadell"}, at=at(1))
    # 23:30 in Madrid on the 3rd is 21:30 UTC, after 10:00 UTC
    store.log(
        BUDGET_ID,
        "import",
        "backdated",
        {"loader": "cobee"},
        at=dt.datetime(2025, 5, 3, 23, 30, tzinfo=madrid),
    )
    store.log(BUDGET_ID, "import", "", {"loader": "cobee"}, at=at(2))
    store.log(BUDGET_ID, "reconcile", "not an import", {"loader": "bbva"}, at=at(4))
    store.log(BUDGET_ID, "import", "no bank", {"loader": 3}, at=at(4))
    store.log(BUDGET_ID, "import", "no details", at=at(4))
    store.log(OTHER_BUDGET_ID, "import", "elsewhere", {"loader": "sabadell"}, at=at(5))

    assert store.last_import_per_loader(BUDGET_ID) == {
        "sabadell": at(3),
        "cobee": at(3, 21) + dt.timedelta(minutes=30),
    }
    assert store.last_import_per_loader("unknown") == {}
