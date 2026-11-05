import asyncio
import datetime as dt
import itertools
import uuid
from collections.abc import Callable
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from nicegui import ui
from nicegui.testing.user import User
from pytest_mock import MockerFixture
from ynab import (
    AccountResponse,
    AccountResponseData,
    AccountsResponse,
    AccountsResponseData,
    TransactionClearedStatus,
    TransactionsResponse,
    TransactionsResponseData,
)

from tests.factories import AccountFactory, TransactionDetailFactory
from tests.helpers.ynab_api import YnabClientStub
from ynab_unlinked.buckets import Bucket
from ynab_unlinked.config import ClearedStatus, DebtMapping, LatestConfig, TrackedAccount
from ynab_unlinked.core.balances import Adjustment
from ynab_unlinked.store import Store, StoredTransaction
from ynab_unlinked.web import theme
from ynab_unlinked.web.state import AppState, state
from ynab_unlinked.web.views import networth
from ynab_unlinked.web.views.networth import by_hand_pill, last_set, range_start
from ynab_unlinked.ynab_api import Client

pytestmark = pytest.mark.version("V4")

BUDGET_ID = "00000000-0000-0000-0000-000000000001"
INDEXA = str(uuid.UUID(int=21))
IBKR = str(uuid.UUID(int=22))
SAVINGS = str(uuid.UUID(int=23))
CHECKING = str(uuid.UUID(int=24))
CARD = str(uuid.UUID(int=25))
ADJUSTMENT_PAYEE = "Balance Adjustment"

TODAY = dt.date.today()


def ago(days: int) -> dt.date:
    return TODAY - dt.timedelta(days=days)


# (account, days ago, amount in milliunits, payee)
HISTORY = [
    (INDEXA, 400, 40_000_000, "Starting Balance"),
    (INDEXA, 9, 6_300_000, ADJUSTMENT_PAYEE),
    (IBKR, 400, 20_000_000, "Starting Balance"),
    (IBKR, 41, 1_500_000, ADJUSTMENT_PAYEE),
    # A dividend after the last adjustment does not make the balance fresh
    (IBKR, 5, 280_000, "Dividend"),
    (SAVINGS, 200, 12_400_000, "Starting Balance"),
    (CHECKING, 200, 2_500_000, "Starting Balance"),
    (CHECKING, 10, -500_000, "Mercadona"),
    (CARD, 20, -300_000, "Amazon"),
]
NAMES = {
    INDEXA: "📈 INDEXA",
    IBKR: "📈 IBKR",
    SAVINGS: "💰 Savings",
    CHECKING: "💶 Checking",
    CARD: "💳 Oro",
}
TYPES = {
    INDEXA: "otherAsset",
    IBKR: "otherAsset",
    SAVINGS: "savings",
    CHECKING: "checking",
    CARD: "creditCard",
}


def serve(ynab_api: YnabClientStub, rows: list[tuple[str, int, int, str]]) -> None:
    """Make YNAB answer a sync with these transactions and the balances they add up to."""
    ids = (f"t{n}" for n in itertools.count())
    balances = dict.fromkeys(TYPES, 0)
    for account, _, amount, _ in rows:
        balances[account] += amount
    ynab_api.api("transactions").get_transactions.return_value = TransactionsResponse(
        data=TransactionsResponseData(
            transactions=[
                TransactionDetailFactory(
                    id=next(ids),
                    account_id=uuid.UUID(account),
                    var_date=ago(days),
                    amount=amount,
                    payee_name=payee,
                )
                for account, days, amount, payee in rows
            ],
            server_knowledge=1,
        )
    )
    ynab_api.api("accounts").get_accounts.return_value = AccountsResponse(
        data=AccountsResponseData(
            accounts=[
                AccountFactory(
                    id=uuid.UUID(account),
                    name=NAMES[account],
                    type=TYPES[account],
                    balance=balance,
                )
                for account, balance in balances.items()
            ],
            server_knowledge=1,
        )
    )
    serve_live(ynab_api, balances)


def serve_live(ynab_api: YnabClientStub, balances: dict[str, int]) -> None:
    """Make YNAB answer GET /accounts/{id} with these balances."""

    def account_by_id(plan_id: str, account_id: uuid.UUID) -> AccountResponse:
        account = str(account_id)
        return AccountResponse(
            data=AccountResponseData(
                account=AccountFactory(
                    id=account_id,
                    name=NAMES[account],
                    type=TYPES[account],
                    balance=balances[account],
                )
            )
        )

    ynab_api.api("accounts").get_account_by_id.side_effect = account_by_id


@pytest.fixture
def tracked(config_v4: LatestConfig) -> LatestConfig:
    """Five tracked accounts, two by hand, the card netted into checking."""
    config_v4.accounts = [
        TrackedAccount(
            id=INDEXA, name="📈 INDEXA", type="otherAsset", bucket=Bucket.ASSETS, track_balance=True
        ),
        TrackedAccount(
            id=IBKR, name="📈 IBKR", type="otherAsset", bucket=Bucket.ASSETS, track_balance=True
        ),
        TrackedAccount(id=SAVINGS, name="💰 Savings", type="savings", bucket=Bucket.SAVINGS),
        TrackedAccount(id=CHECKING, name="💶 Checking", type="checking", bucket=Bucket.CASH),
        TrackedAccount(id=CARD, name="💳 Oro", type="creditCard", bucket=Bucket.DEBT),
    ]
    config_v4.debt_mappings = [DebtMapping(debt_account_id=CARD, mapped_to=[CHECKING])]
    config_v4.adjustments.memo = "Set by hand"
    config_v4.adjustments.cleared = ClearedStatus.RECONCILED
    config_v4.save()
    return config_v4


@pytest.fixture
def seeded(tracked: LatestConfig, ynab_api: YnabClientStub, store_file: Path) -> Store:
    """The store after a sync of `HISTORY`."""
    serve(ynab_api, HISTORY)
    store = Store(store_file)
    store.sync(Client("api-key"), BUDGET_ID)
    return store


@pytest.fixture
def no_sync(mocker: MockerFixture) -> MagicMock:
    return mocker.patch.object(AppState, "sync_in_background")


def texts(user: User, marker: str) -> str:
    """Every label under the elements with this marker, joined by spaces."""
    elements = user.find(marker=marker).elements
    assert elements, f"nothing marked {marker!r}"
    return " ".join(
        child.text
        for element in elements
        for child in element.descendants(include_self=True)
        if isinstance(child, ui.label)
    )


def chart_series(user: User, marker: str = "nw-chart") -> list[dict]:
    chart = user.find(marker=marker).elements.pop()
    assert isinstance(chart, ui.echart)
    return chart.options["series"]


async def eventually(check: Callable[[], bool]) -> None:
    """Wait for a background handler (a click that reads the store) to finish."""
    for _ in range(100):
        if check():
            return
        await asyncio.sleep(0.02)
    assert check()


async def open_networth(user: User) -> None:
    await user.open("/networth")
    await user.should_see(marker="nw-figure", retries=20)


async def test_hero_and_tiles_show_the_netted_buckets(seeded: Store, no_sync, user: User):
    await open_networth(user)

    # 46,300 + 21,780 assets, 12,400 savings, 2,000 checking minus the 300 card
    assert texts(user, "nw-figure") == "82,180.00€"
    assert texts(user, "tile-assets") == "Assets 68,080.00€ 82.8% of net worth"
    assert texts(user, "tile-savings") == "Savings 12,400.00€ 15.1%"
    assert texts(user, "tile-cash") == "Cash 1,700.00€ 2.1% · after debt"
    assert texts(user, "tile-debt") == "Debt -300.00€ netted into 1 cash account"
    # Debt shows its raw balance and no share; checking is shown after netting
    assert texts(user, f"row-{CARD}") == "💳 Oro -300.00€ netted"
    assert "1,700.00€ 2.1%" in texts(user, f"row-{CHECKING}")


async def test_without_account_settings_every_open_account_counts_with_its_defaults(
    config_v4: LatestConfig, ynab_api: YnabClientStub, store_file: Path, no_sync, user: User
):
    # A config migrated from V3 has no account settings; the debt mapping still applies
    config_v4.debt_mappings = [DebtMapping(debt_account_id=CARD, mapped_to=[CHECKING])]
    config_v4.save()
    state().reload()
    serve(ynab_api, HISTORY)
    Store(store_file).sync(Client("api-key"), BUDGET_ID)

    await open_networth(user)

    assert texts(user, "nw-figure") == "82,180.00€"
    assert texts(user, "tile-debt") == "Debt -300.00€ netted into 1 cash account"
    # Investment and other asset accounts are entered by hand unless the user says otherwise
    for account in (INDEXA, IBKR):
        assert "always" in user.find(marker=f"edit-{account}").elements.pop().classes
    assert "always" not in user.find(marker=f"edit-{CHECKING}").elements.pop().classes


async def test_an_account_left_out_does_not_count(
    config_v4: LatestConfig, ynab_api: YnabClientStub, store_file: Path, no_sync, user: User
):
    config_v4.accounts = [
        TrackedAccount(
            id=SAVINGS, name="💰 Savings", type="savings", bucket=Bucket.SAVINGS, counted=False
        )
    ]
    config_v4.save()
    state().reload()
    serve(ynab_api, HISTORY)
    Store(store_file).sync(Client("api-key"), BUDGET_ID)

    await open_networth(user)

    # 82,180 without the 12,400 of savings; nothing nets the card, its 300 still comes off
    assert texts(user, "nw-figure") == "69,780.00€"
    await user.should_not_see(marker=f"row-{SAVINGS}")


async def test_every_account_has_a_pencil_shown_always_on_by_hand_ones(
    seeded: Store, no_sync, user: User
):
    await open_networth(user)

    for account in (INDEXA, IBKR):
        assert "always" in user.find(marker=f"edit-{account}").elements.pop().classes
    for account in (SAVINGS, CHECKING, CARD):
        assert "always" not in user.find(marker=f"edit-{account}").elements.pop().classes
        await user.should_not_see(marker=f"age-{account}")
    assert texts(user, f"age-{INDEXA}") == "by hand · 9 days ago"
    assert texts(user, f"age-{IBKR}") == "stale · 41 days ago"
    assert "warn" in user.find(marker=f"age-{IBKR}").elements.pop().classes


def _transaction(day: dt.date, payee: str) -> StoredTransaction:
    return StoredTransaction(
        id=f"{day}{payee}",
        account_id=INDEXA,
        date=day,
        amount=1000,
        cleared=TransactionClearedStatus.CLEARED,
        approved=True,
        deleted=False,
        payee_name=payee,
        category_name=None,
        import_id=None,
        memo=None,
        transfer_account_id=None,
    )


@pytest.mark.parametrize(
    ("payees", "expected"),
    [
        ([(40, ADJUSTMENT_PAYEE), (3, "Dividend")], ago(40)),
        ([(40, "Starting Balance"), (3, "Dividend")], ago(3)),
        ([], None),
    ],
    ids=["latest-adjustment-wins", "latest-transaction-without-adjustments", "no-history"],
)
def test_a_by_hand_balance_was_last_set_by_its_latest_adjustment(payees, expected):
    transactions = [_transaction(ago(days), payee) for days, payee in payees]

    assert last_set(transactions, ADJUSTMENT_PAYEE) == expected


@pytest.mark.parametrize(
    ("days", "expected"),
    [
        (0, ("by hand · today", "acc")),
        (30, ("by hand · 30 days ago", "acc")),
        (31, ("stale · 31 days ago", "warn")),
        (None, ("stale · never set", "warn")),
    ],
    ids=["today", "30-days-is-fresh", "31-days-is-stale", "never-set"],
)
def test_a_by_hand_balance_is_stale_after_30_days(days, expected):
    assert by_hand_pill(None if days is None else ago(days), TODAY) == expected


@pytest.mark.parametrize(
    ("key", "today", "expected"),
    [
        ("1M", dt.date(2026, 3, 31), dt.date(2026, 2, 28)),
        ("6M", dt.date(2026, 11, 3), dt.date(2026, 5, 3)),
        ("YTD", dt.date(2026, 11, 3), dt.date(2026, 1, 1)),
        ("1Y", dt.date(2026, 11, 3), dt.date(2025, 11, 3)),
        ("All", dt.date(2026, 11, 3), dt.date(2024, 6, 1)),
    ],
    ids=["month-end-clamped", "6M", "YTD", "1Y", "all-is-the-first-transaction"],
)
def test_range_start(key: str, today: dt.date, expected: dt.date):
    assert range_start(key, today, earliest=dt.date(2024, 6, 1)) == expected


def test_a_range_never_starts_before_the_first_transaction():
    assert range_start("1Y", dt.date(2026, 11, 3), earliest=dt.date(2026, 9, 1)) == dt.date(
        2026, 9, 1
    )


def editor_value(user: User, account: str) -> str:
    field = user.find(marker=f"balance-input-{account}").elements.pop()
    assert isinstance(field, ui.input)
    return str(field.value)


async def edit(user: User, account: str, text: str) -> None:
    user.find(marker=f"edit-{account}").click()
    await user.should_see(marker=f"balance-input-{account}")
    user.find(marker=f"balance-input-{account}").clear().type(text)


async def test_the_pencil_opens_one_editor_prefilled_with_the_balance_in_ynab(
    seeded: Store, no_sync, user: User
):
    await open_networth(user)

    user.find(marker=f"edit-{CHECKING}").click()

    await user.should_see(marker=f"balance-input-{CHECKING}")
    # The balance YNAB has, not the 1,700.00€ shown after netting the card
    assert editor_value(user, CHECKING) == "2,000.00€"
    await user.should_see(marker=f"accept-{CHECKING}")
    await user.should_see(marker=f"cancel-{CHECKING}")

    user.find(marker=f"edit-{INDEXA}").click()

    await user.should_see(marker=f"balance-input-{INDEXA}")
    assert editor_value(user, INDEXA) == "46,300.00€"
    await user.should_not_see(marker=f"balance-input-{CHECKING}")
    assert "1,700.00€" in texts(user, f"row-{CHECKING}")


async def test_accepting_creates_one_adjustment_and_logs_it(
    seeded: Store, no_sync: MagicMock, user: User, mocker: MockerFixture
):
    create = mocker.patch(
        "ynab_unlinked.web.views.networth.data.create_adjustments", return_value=1
    )
    await open_networth(user)

    await edit(user, INDEXA, "46,322.46")
    user.find(marker=f"accept-{INDEXA}").click()
    await user.should_see("📈 INDEXA set to 46,322.46€ (+22.46€)", retries=20)
    await user.should_not_see(marker=f"balance-input-{INDEXA}")

    # Enter accepts too
    await edit(user, IBKR, "20000")
    user.find(marker=f"balance-input-{IBKR}").trigger("keydown.enter")
    await user.should_see("📈 IBKR set to 20,000.00€ (-1,780.00€)", retries=20)

    assert create.call_count == 2
    sent = [call.args for call in create.call_args_list]
    assert [args[2] for args in sent] == [
        [Adjustment(account_id=INDEXA, old_balance=46_300_000, new_balance=46_322_460)],
        [Adjustment(account_id=IBKR, old_balance=21_780_000, new_balance=20_000_000)],
    ]
    _, budget_id, _, memo, payee, cleared, date = sent[0]
    assert budget_id == BUDGET_ID
    assert (memo, payee, cleared, date) == (
        "Set by hand",
        ADJUSTMENT_PAYEE,
        TransactionClearedStatus.RECONCILED,
        TODAY,
    )
    no_sync.assert_called()

    activity = seeded.activity(BUDGET_ID)
    assert [(a.kind, a.message) for a in reversed(activity)] == [
        ("adjustment", "Balance of 📈 INDEXA set to 46,322.46€ (+22.46€)"),
        ("adjustment", "Balance of 📈 IBKR set to 20,000.00€ (-1,780.00€)"),
    ]
    assert activity[0].details == {
        "account_id": IBKR,
        "account_name": "📈 IBKR",
        "old": 21_780_000,
        "new": 20_000_000,
        "amount": -1_780_000,
    }


async def test_any_tracked_account_can_be_set_not_only_by_hand_ones(
    seeded: Store, no_sync, user: User, mocker: MockerFixture
):
    create = mocker.patch(
        "ynab_unlinked.web.views.networth.data.create_adjustments", return_value=1
    )
    await open_networth(user)

    await edit(user, CARD, "-250")
    user.find(marker=f"accept-{CARD}").click()

    await user.should_see("💳 Oro set to -250.00€ (+50.00€)", retries=20)
    assert create.call_args.args[2] == [
        Adjustment(account_id=CARD, old_balance=-300_000, new_balance=-250_000)
    ]


async def test_the_same_balance_creates_nothing(
    seeded: Store, no_sync, user: User, mocker: MockerFixture
):
    create = mocker.patch("ynab_unlinked.web.views.networth.data.create_adjustments")
    await open_networth(user)

    await edit(user, INDEXA, "46300")
    user.find(marker=f"accept-{INDEXA}").click()

    await user.should_see("No change")
    await user.should_not_see(marker=f"balance-input-{INDEXA}")
    create.assert_not_called()
    assert seeded.activity(BUDGET_ID) == []


async def test_text_that_is_not_an_amount_keeps_the_editor_open(
    seeded: Store, no_sync, user: User, mocker: MockerFixture
):
    create = mocker.patch("ynab_unlinked.web.views.networth.data.create_adjustments")
    await open_networth(user)

    await edit(user, INDEXA, "lots")
    user.find(marker=f"accept-{INDEXA}").click()

    await user.should_see(marker=f"balance-hint-{INDEXA}")
    assert texts(user, f"balance-hint-{INDEXA}") == "Not an amount"
    await user.should_see(marker=f"balance-input-{INDEXA}")
    create.assert_not_called()

    user.find(marker=f"balance-input-{INDEXA}").type("4")
    await user.should_not_see(marker=f"balance-hint-{INDEXA}")


async def test_a_ynab_error_keeps_the_balance_and_logs_nothing(
    seeded: Store, no_sync, user: User, mocker: MockerFixture
):
    mocker.patch(
        "ynab_unlinked.web.views.networth.data.create_adjustments",
        side_effect=RuntimeError("offline"),
    )
    await open_networth(user)

    await edit(user, INDEXA, "47,000")
    user.find(marker=f"accept-{INDEXA}").click()

    await user.should_see(
        "The balance of 📈 INDEXA was not set. Could not reach YNAB: offline", retries=20
    )
    assert editor_value(user, INDEXA) == "47,000"
    assert seeded.activity(BUDGET_ID) == []


async def test_the_adjustment_starts_from_the_balance_ynab_has_now(
    seeded: Store, no_sync: MagicMock, ynab_api: YnabClientStub, user: User, mocker: MockerFixture
):
    create = mocker.patch(
        "ynab_unlinked.web.views.networth.data.create_adjustments", return_value=1
    )
    await open_networth(user)
    # A transaction entered on the phone after the last sync: YNAB has 100.00€ more
    serve_live(ynab_api, {INDEXA: 46_400_000})

    await edit(user, INDEXA, "47,000")
    user.find(marker=f"accept-{INDEXA}").click()

    await user.should_see("📈 INDEXA set to 47,000.00€ (+600.00€)", retries=20)
    assert create.call_args.args[2] == [
        Adjustment(account_id=INDEXA, old_balance=46_400_000, new_balance=47_000_000)
    ]
    [entry] = seeded.activity(BUDGET_ID)
    assert entry.details["old"] == 46_400_000
    assert entry.details["amount"] == 600_000


async def test_nothing_is_written_when_ynab_already_has_the_balance(
    seeded: Store, no_sync: MagicMock, ynab_api: YnabClientStub, user: User, mocker: MockerFixture
):
    create = mocker.patch("ynab_unlinked.web.views.networth.data.create_adjustments")
    await open_networth(user)
    serve_live(ynab_api, {INDEXA: 47_000_000})

    await edit(user, INDEXA, "47,000")
    user.find(marker=f"accept-{INDEXA}").click()

    await user.should_see("No change", retries=20)
    await user.should_not_see(marker=f"balance-input-{INDEXA}")
    create.assert_not_called()
    assert seeded.activity(BUDGET_ID) == []
    no_sync.assert_called()


@pytest.mark.parametrize("how", ["cross", "escape"])
async def test_cancelling_the_editor_creates_nothing(
    seeded: Store, no_sync, user: User, mocker: MockerFixture, how: str
):
    create = mocker.patch("ynab_unlinked.web.views.networth.data.create_adjustments")
    await open_networth(user)
    await edit(user, INDEXA, "47,000")

    if how == "cross":
        user.find(marker=f"cancel-{INDEXA}").click()
    else:
        user.find(marker=f"balance-input-{INDEXA}").trigger("keydown.escape")

    await user.should_not_see(marker=f"balance-input-{INDEXA}")
    assert "46,300.00€" in texts(user, f"row-{INDEXA}")
    create.assert_not_called()


def _names(series: list[dict]) -> list[str]:
    return [item["name"] for item in series]


def chip_swatch(user: User, account: str) -> str | None:
    """The background of a chip's colour swatch, None when it shows none."""
    chip = user.find(marker=f"pick-{account}").elements.pop()
    swatches = [e for e in chip.descendants() if "yul-swatch" in e.classes]
    return swatches[0].style["background"] if swatches else None


async def test_grouping_and_the_account_chips_rebuild_the_chart(seeded: Store, no_sync, user: User):
    await open_networth(user)
    assert _names(chart_series(user)) == ["Net worth"]
    await user.should_not_see(marker="account-picker")

    grouping = user.find(marker="grouping").elements.pop()
    assert isinstance(grouping, ui.select)
    grouping.set_value("type")
    assert _names(chart_series(user)) == ["Assets", "Savings", "Cash"]

    grouping.set_value("account")
    await user.should_see(marker="account-picker")
    # The four largest accounts after netting, debt left out
    series = chart_series(user)
    assert _names(series) == ["📈 INDEXA", "📈 IBKR", "💰 Savings", "💶 Checking"]
    colours = {item["name"]: item["color"] for item in series}
    assert list(colours.values()) == list(theme.SERIES[:4])
    assert texts(user, "pick-count") == "Accounts · 4 of 6"
    # Chips follow the table and wear the colour of their series
    order = [INDEXA, IBKR, SAVINGS, CHECKING, CARD]
    assert [texts(user, f"pick-{account}") for account in order] == [NAMES[a] for a in order]
    assert chip_swatch(user, IBKR) == "var(--series-2)"
    assert chip_swatch(user, CARD) is None
    assert "on" not in user.find(marker=f"pick-{CARD}").elements.pop().classes

    user.find(marker=f"pick-{IBKR}").click()
    assert texts(user, "pick-count") == "Accounts · 3 of 6"
    assert chip_swatch(user, IBKR) is None
    user.find(marker=f"pick-{CARD}").click()

    # Accounts keep their colour; the card takes the slot IBKR left
    series = chart_series(user)
    assert {item["name"]: item["color"] for item in series} == {
        "📈 INDEXA": colours["📈 INDEXA"],
        "💳 Oro": colours["📈 IBKR"],
        "💰 Savings": colours["💰 Savings"],
        "💶 Checking": colours["💶 Checking"],
    }
    assert chip_swatch(user, CARD) == "var(--series-2)"
    assert "on" in user.find(marker=f"pick-{CARD}").elements.pop().classes


async def test_at_the_limit_unpicked_chips_say_why_they_cannot_be_added(
    seeded: Store, no_sync, user: User, monkeypatch: pytest.MonkeyPatch
):
    # The fixture has five accounts; a limit of four is reached by the default pick
    monkeypatch.setattr(networth.data, "MAX_PICKED", 4)
    await open_networth(user)
    grouping = user.find(marker="grouping").elements.pop()
    assert isinstance(grouping, ui.select)
    grouping.set_value("account")
    assert texts(user, "pick-count") == "Accounts · 4 of 4"
    card = user.find(marker=f"pick-{CARD}").elements.pop()
    assert "off" in card.classes
    assert card.props["title"] == "Remove one to add another"

    user.find(marker=f"pick-{CARD}").click()

    assert texts(user, "pick-count") == "Accounts · 4 of 4"
    assert "💳 Oro" not in _names(chart_series(user))

    user.find(marker=f"pick-{IBKR}").click()
    card = user.find(marker=f"pick-{CARD}").elements.pop()
    assert "off" not in card.classes
    assert "title" not in card.props
    user.find(marker=f"pick-{CARD}").click()

    assert "💳 Oro" in _names(chart_series(user))


async def test_range_pills_change_the_chart_dates(seeded: Store, no_sync, user: User):
    await open_networth(user)
    first_day = chart_series(user)[0]["data"][0][0]
    assert dt.date.fromisoformat(first_day) == range_start("6M", TODAY, ago(400))

    start = range_start("1M", TODAY, ago(400))
    user.find(marker="range-1M").click()
    await eventually(lambda: len(chart_series(user)[0]["data"]) == (TODAY - start).days + 1)
    data = chart_series(user)[0]["data"]
    assert data[-1] == [TODAY.isoformat(), 82_180.0]

    user.find(marker="range-All").click()
    await eventually(lambda: chart_series(user)[0]["data"][0][0] < start.isoformat())
    data = chart_series(user)[0]["data"]
    # Over a year: one point a week from the first transaction, ending today
    assert dt.date.fromisoformat(data[0][0]) - ago(400) < dt.timedelta(days=7)
    assert len(data) < 70
    assert data[-1] == [TODAY.isoformat(), 82_180.0]
    first = dt.date.fromisoformat(data[0][0])
    assert texts(user, "nw-delta") == f"▲ 22,180.00€ since {first.day} {first:%b %Y}"


async def test_the_account_drawer_lists_its_transactions(seeded: Store, no_sync, user: User):
    await open_networth(user)

    user.find(marker=f"name-{INDEXA}").click()

    await user.should_see(marker="nw-drawer", retries=20)
    rows = [texts(user, "drawer-tx")]
    assert len(user.find(marker="drawer-tx").elements) == 2
    assert ADJUSTMENT_PAYEE in rows[0]
    drawer_series = chart_series(user, "drawer-chart")
    assert drawer_series[0]["data"][-1] == [TODAY.isoformat(), 46_300.0]


async def test_the_first_sync_fills_the_view_when_it_lands(
    tracked: LatestConfig, ynab_api: YnabClientStub, user: User
):
    serve(ynab_api, HISTORY)

    await user.open("/networth")

    await user.should_see("First sync running…")
    await user.should_see(marker="nw-figure", retries=60)
    assert texts(user, "nw-figure") == "82,180.00€"
