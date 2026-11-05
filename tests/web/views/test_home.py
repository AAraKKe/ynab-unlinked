import dataclasses
import datetime as dt
from collections.abc import Callable
from pathlib import Path
from unittest.mock import PropertyMock

import pytest
from nicegui import ui
from nicegui.elements.upload_files import SmallFileUpload
from nicegui.testing.user import User
from pytest_mock import MockerFixture
from ynab import TransactionClearedStatus

from tests.helpers.store import upsert
from tests.helpers.ynab_api import YnabClientStub
from ynab_unlinked.buckets import Bucket
from ynab_unlinked.config import DebtMapping, LatestConfig, TrackedAccount
from ynab_unlinked.store import Activity, Store, StoredAccount, StoredTransaction
from ynab_unlinked.web.state import AppState, state
from ynab_unlinked.web.views import home
from ynab_unlinked.ynab_api import Client

pytestmark = pytest.mark.version("V4")

CLEARED = TransactionClearedStatus.CLEARED
RECONCILED = TransactionClearedStatus.RECONCILED
NOW = dt.datetime.now(dt.UTC)
TODAY = dt.date.today()
LOADERS = ("sabadell", "cobee", "test")  # the loaders in the V4 config asset


def days_ago(days: int) -> dt.date:
    return TODAY - dt.timedelta(days=days)


def account(id: str, balance: int, *, closed: bool = False) -> StoredAccount:
    return StoredAccount(
        id=id,
        name=id.title(),
        type="checking",
        closed=closed,
        on_budget=True,
        balance=balance,
        cleared_balance=balance,
        uncleared_balance=0,
    )


def transaction(
    id: str,
    account_id: str,
    day: dt.date,
    amount: int,
    *,
    payee: str = "Shop",
    cleared: TransactionClearedStatus = RECONCILED,
) -> StoredTransaction:
    return StoredTransaction(
        id=id,
        account_id=account_id,
        date=day,
        amount=amount,
        cleared=cleared,
        approved=True,
        deleted=False,
        payee_name=payee,
        category_name=None,
        import_id=None,
        memo=None,
        transfer_account_id=None,
    )


def log_import(store: Store, budget_id: str, loader: str, days: int) -> None:
    store.log(
        budget_id,
        "import",
        f"Imported 2 transactions to Checking from {loader}.txt",
        {"loader": loader, "file": f"{loader}.txt", "created": 2},
        at=NOW - dt.timedelta(days=days),
    )


@pytest.fixture
def budget(config_v4: LatestConfig) -> LatestConfig:
    """Checking and savings, a card netted from checking and a broker updated by hand."""
    config_v4.accounts = [
        TrackedAccount(id="checking", name="Checking", type="checking", bucket=Bucket.CASH),
        TrackedAccount(id="savings", name="Savings", type="savings", bucket=Bucket.SAVINGS),
        TrackedAccount(id="card", name="Card", type="creditCard", bucket=Bucket.DEBT),
        TrackedAccount(
            id="broker", name="Broker", type="otherAsset", bucket=Bucket.ASSETS, track_balance=True
        ),
    ]
    config_v4.debt_mappings = [DebtMapping(debt_account_id="card", mapped_to=["checking"])]
    config_v4.save()
    return config_v4


@pytest.fixture
def last_imports() -> dict[str, int]:
    """Days since each loader was last used from the app. Parametrize it to change them."""
    return dict.fromkeys(LOADERS, 3)


@pytest.fixture
def store(
    budget: LatestConfig, store_file: Path, ynab_api: YnabClientStub, last_imports: dict[str, int]
) -> Store:
    """A store that synced once and holds a quiet budget: nothing needs attention.

    Request it, and change it, before `user`, which loads the state from it.
    """
    transactions = ynab_api.api("transactions").get_transactions.return_value
    transactions.data.transactions = []
    transactions.data.server_knowledge = 1
    ynab_api.api("accounts").get_accounts.return_value.data.accounts = []
    store = Store(store_file)
    store.sync(Client(api_key="an-api-key"), budget.budget.id)

    upsert(
        store,
        budget.budget.id,
        accounts=[
            account("checking", 1_000_000),
            account("savings", 500_000),
            account("card", -200_000),
            account("broker", 3_000_000),
        ],
        transactions=[
            transaction("c1", "checking", days_ago(100), 900_000, payee="Starting Balance"),
            transaction("c2", "checking", days_ago(10), 100_000),
            transaction("s1", "savings", days_ago(100), 500_000, payee="Starting Balance"),
            transaction("d1", "card", days_ago(100), -200_000, payee="Starting Balance"),
            transaction("b1", "broker", days_ago(100), 3_000_000, payee="Balance Adjustment"),
            transaction("b2", "broker", days_ago(3), 0, payee="Balance Adjustment"),
        ],
    )
    for loader, days in last_imports.items():
        log_import(store, budget.budget.id, loader, days=days)
    return store


async def _home(user: User) -> None:
    await user.open("/")
    await user.should_see(marker="activity", retries=20)


@pytest.mark.parametrize(
    ("reconciled_days_ago", "delta"),
    [
        # No reconcile yet: the change over 30 days, which includes the +100 ten days ago
        (None, "▲ 100.00€"),
        (5, "No change"),
        # Before the 90 day sparkline window, read from its own point
        (120, "▲ 4,300.00€"),
    ],
    ids=["30-days", "since-reconcile", "reconcile-before-the-sparkline"],
)
async def test_the_hero_shows_net_worth_with_debt_netted_and_the_change_since_the_last_reconcile(
    store: Store, budget: LatestConfig, user: User, reconciled_days_ago: int | None, delta: str
):
    if reconciled_days_ago is not None:
        store.log(
            budget.budget.id,
            "reconcile",
            "Reconciled 3 transactions in 1 account",
            {"count": 3},
            at=NOW - dt.timedelta(days=reconciled_days_ago),
        )

    await _home(user)

    # 1000 + 500 + 3000 - 200 of card netted from checking
    await user.should_see("4,300.00€")
    await user.should_see(delta)
    await user.should_see(marker="sparkline")


async def test_the_hero_opens_net_worth(store: Store, user: User):
    await _home(user)

    user.find(marker="hero").click()

    await user.should_see("All your accounts in one figure")


def unreconciled(store: Store, budget_id: str) -> None:
    upsert(
        store,
        budget_id,
        transactions=[
            transaction("u1", "checking", days_ago(2), -5_000, cleared=CLEARED),
            transaction("u2", "savings", days_ago(2), -5_000, cleared=CLEARED),
        ],
    )


def unreconciled_in_closed_account(store: Store, budget_id: str) -> None:
    upsert(
        store,
        budget_id,
        accounts=[account("old", 0, closed=True)],
        transactions=[transaction("u1", "old", days_ago(2), -5_000, cleared=CLEARED)],
    )


def stale_balance(store: Store, budget_id: str) -> None:
    upsert(
        store,
        budget_id,
        transactions=[
            transaction("b2", "broker", days_ago(40), 0, payee="Balance Adjustment"),
            # Only adjustments count as updates when there are any
            transaction("b3", "broker", days_ago(1), 10, payee="Dividend"),
        ],
    )


def _markers(user: User, marker: str) -> list[str]:
    """Every marker under the element marked `marker`, in page order."""
    [root] = user.find(marker=marker).elements
    return [m for child in root.descendants() for m in child._markers]


def _text(user: User, marker: str) -> str:
    [element] = user.find(marker=marker).elements
    assert isinstance(element, ui.label)
    return element.text


async def test_home_shows_net_worth_then_import_then_what_needs_you_and_activity_aside(
    store: Store, user: User
):
    await _home(user)

    order = [
        m for m in _markers(user, "home") if m in {"hero", "home-import", "needs-you", "activity"}
    ]
    assert order == ["hero", "home-import", "needs-you", "activity"]
    import_section = _markers(user, "home-import")
    assert "dropzone" in import_section
    assert "last-imports" in import_section
    await user.should_see("Import")
    await user.should_see("Needs you")


@pytest.mark.parametrize(
    ("make", "card", "text"),
    [
        (unreconciled, "attention-unreconciled", "to reconcile in 2 accounts"),
        (stale_balance, "attention-stale", "set by hand, older than 30 days: Broker"),
    ],
    ids=["unreconciled", "stale-balance"],
)
async def test_needs_you_shows_a_card_for_what_is_waiting(
    store: Store,
    budget: LatestConfig,
    user: User,
    make: Callable[[Store, str], None],
    card: str,
    text: str,
):
    make(store, budget.budget.id)

    await _home(user)

    shown = {m for m in _markers(user, "needs-you") if m.startswith("attention-")}
    assert shown == {card}
    await user.should_see(text)
    await user.should_not_see(marker="nothing-waiting")


async def test_the_reconcile_card_counts_transactions_and_opens_reconcile(
    store: Store, budget: LatestConfig, user: User
):
    unreconciled(store, budget.budget.id)
    await _home(user)

    await user.should_see("2 transactions")
    await user.should_see("Reconcile →")

    user.find(marker="attention-unreconciled").click()

    await user.should_see(marker="reconcile", retries=20)
    assert user.back_history[-1] == "/reconcile"


@pytest.mark.parametrize(
    "make",
    [
        lambda store, budget_id: None,
        unreconciled_in_closed_account,
        lambda store, budget_id: store.log(budget_id, "config", "Settings imported", {}),
    ],
    ids=["quiet", "unreconciled-in-closed-account", "settings-changed"],
)
async def test_with_nothing_waiting_needs_you_says_so_in_one_quiet_line(
    store: Store, budget: LatestConfig, user: User, make: Callable[[Store, str], None]
):
    make(store, budget.budget.id)

    await _home(user)

    await user.should_see(
        "Nothing waiting. Drop a statement or check back after your next import.",
        marker="nothing-waiting",
    )
    await user.should_not_see(marker="attention")
    assert not [m for m in _markers(user, "needs-you") if m.startswith("attention-")]


@pytest.mark.parametrize(
    ("last_imports", "expected"),
    [
        (
            dict.fromkeys(LOADERS, 3),
            "Last imports · Cobee 3 days ago · Sabadell 3 days ago",
        ),
        (
            {"sabadell": 40, "test": 1},
            f"Last imports · Cobee never · Sabadell {home.short_date(days_ago(40), TODAY)}",
        ),
        (
            {"sabadell": 1, "cobee": 0},
            "Last imports · Cobee today · Sabadell yesterday",
        ),
    ],
    ids=["recent", "never-and-long-ago", "today-and-yesterday"],
)
async def test_the_last_imports_line_lists_the_banks_in_registry_order(
    store: Store, user: User, expected: str
):
    await _home(user)

    # BBVA is not set up in the config and the "test" loader is not a bank yul ships
    assert _text(user, "last-imports") == expected
    # No card per bank: the line is the only place they show up
    assert not [m for m in _markers(user, "home") if m.startswith("attention-loader")]


async def test_a_bank_turned_off_is_left_out_of_the_last_imports(
    store: Store, budget: LatestConfig, user: User
):
    budget.loaders["sabadell"].enabled = False
    budget.save()
    state().reload()

    await _home(user)

    assert _text(user, "last-imports") == "Last imports · Cobee 3 days ago"


async def test_with_every_bank_turned_off_there_is_no_last_imports_line(
    store: Store, budget: LatestConfig, user: User
):
    for loader in budget.loaders.values():
        loader.enabled = False
    budget.save()
    state().reload()

    await _home(user)

    await user.should_see(marker="dropzone")
    await user.should_not_see(marker="last-imports")


@pytest.mark.parametrize(
    ("left_out", "figure"),
    [
        # 1000 + 500 + 3000 - 200 of card netted from checking; the closed account is ignored
        ((), "4,300.00€"),
        (("savings",), "3,800.00€"),
    ],
    ids=["every-open-account", "savings-left-out"],
)
async def test_without_account_settings_every_open_account_counts(
    store: Store, budget: LatestConfig, user: User, left_out: tuple[str, ...], figure: str
):
    upsert(
        store,
        budget.budget.id,
        accounts=[
            dataclasses.replace(account("card", -200_000), type="creditCard"),
            account("old", 99_000_000, closed=True),
        ],
    )
    budget.accounts = [
        TrackedAccount(id=id, name=id.title(), type="checking", bucket=Bucket.CASH, counted=False)
        for id in left_out
    ]
    budget.save()
    state().reload()

    await _home(user)

    await user.should_see(figure)
    # Picking accounts is a job for Settings, not a card on Home
    await user.should_see(marker="nothing-waiting")


async def test_recent_activity_is_newest_first_with_counts_in_bold(
    store: Store, budget: LatestConfig, user: User
):
    store.clear(budget.budget.id, activity=True)
    store.log(
        budget.budget.id,
        "reconcile",
        "Reconciled 21 transactions in 3 accounts",
        {"count": 21},
        at=NOW - dt.timedelta(days=2),
    )
    store.log(
        budget.budget.id,
        "sync",
        "Synced · 6 changes from YNAB",
        {"changes": 6, "full": False},
        at=NOW - dt.timedelta(minutes=2),
    )
    store.log(
        budget.budget.id,
        "adjustment",
        "Balance of Broker set to 3,000.00€ (+10.00€)",
        {},
        at=NOW - dt.timedelta(days=1),
    )

    await _home(user)

    messages = [
        element.content
        for element in sorted(user.find(marker="activity-message").elements, key=lambda e: e.id)
        if isinstance(element, ui.html)
    ]
    assert messages == [
        "Synced · <b>6</b> changes from YNAB",
        "Balance of Broker set to 3,000.00€ (+10.00€)",
        "Reconciled <b>21</b> transactions in 3 accounts",
    ]
    await user.should_see("2 min")


async def test_recent_activity_has_an_empty_state(store: Store, budget: LatestConfig, user: User):
    store.clear(budget.budget.id, activity=True)

    await _home(user)

    await user.should_see(marker="activity-empty")


async def test_files_dropped_on_home_go_to_the_import_view(store: Store, user: User):
    await _home(user)
    upload = user.find(marker="dropzone").elements.pop()
    assert isinstance(upload, ui.upload)

    statement = SmallFileUpload(name="movimientos.txt", content_type="text/plain", _data=b"x")
    await upload.handle_uploads([statement])

    await user.should_see("movimientos.txt", marker="file-1", retries=20)
    assert user.back_history[-1] == "/import"


async def test_the_top_bar_import_button_opens_the_import_view(store: Store, user: User):
    await _home(user)

    user.find(marker="top-import").click()

    await user.should_see("Files → Review → Done")
    assert user.back_history[-1] == "/import"


async def test_home_waits_for_the_first_sync_and_then_shows_the_budget(
    budget: LatestConfig, user: User, mocker: MockerFixture, store_file: Path
):
    mocker.patch.object(home.view, "SYNC_POLL_SECONDS", 0.05)
    syncing = mocker.patch.object(AppState, "syncing", new_callable=PropertyMock)
    syncing.return_value = True

    await user.open("/")
    await user.should_see("First sync running…", retries=20)

    store = Store(store_file)
    upsert(store, budget.budget.id, accounts=[account("checking", 1_000_000)])
    state().last_sync = NOW
    syncing.return_value = False

    await user.should_not_see("First sync running…", retries=40)
    await user.should_see("1,000.00€")


@pytest.mark.parametrize(
    ("ago", "expected"),
    [
        (dt.timedelta(seconds=30), "just now"),
        (dt.timedelta(minutes=2, seconds=5), "2 min"),
        (dt.timedelta(hours=5), "5 h"),
    ],
    ids=["seconds", "minutes", "hours"],
)
def test_relative_time_for_recent_entries(ago: dt.timedelta, expected: str):
    assert home.relative_time(NOW - ago, NOW) == expected


def test_relative_time_shows_the_day_for_older_entries_and_the_year_when_it_differs():
    now = dt.datetime(2026, 11, 3, 12, tzinfo=dt.UTC)

    assert home.relative_time(dt.datetime(2026, 10, 29, 12, tzinfo=dt.UTC), now) == "29 Oct"
    assert home.relative_time(dt.datetime(2025, 12, 30, 12, tzinfo=dt.UTC), now) == "30 Dec 2025"


@pytest.mark.parametrize(
    ("kind", "message", "details", "expected"),
    [
        (
            "import",
            "Imported 13 transactions to Oro 13 from <movs>.txt",
            {"created": 13, "file": "<movs>.txt"},
            "Imported <b>13</b> transactions to Oro 13 from "
            '<span class="yul-mono">&lt;movs&gt;.txt</span>',
        ),
        # The count must not be found inside an amount
        (
            "sync",
            "Synced 1,6 · 6 changes",
            {"changes": 6},
            "Synced 1,6 · <b>6</b> changes",
        ),
        ("adjustment", "Balance set to 6.00€", {"amount": 6}, "Balance set to 6.00€"),
        ("reconcile", "Reconciled", {"count": True}, "Reconciled"),
    ],
    ids=["import", "count-next-to-an-amount", "no-count-for-the-kind", "not-a-number"],
)
def test_activity_message_markup(kind: str, message: str, details: dict, expected: str):
    entry = Activity(at=NOW, kind=kind, message=message, details=details)

    assert home.message_markup(entry) == expected
