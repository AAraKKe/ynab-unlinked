import datetime as dt
import uuid
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from nicegui.testing.user import User
from pytest_mock import MockerFixture
from ynab import (
    AccountsResponse,
    AccountsResponseData,
    TransactionsResponse,
    TransactionsResponseData,
)

from tests.factories import AccountFactory, TransactionDetailFactory
from tests.helpers.ynab_api import YnabClientStub
from tests.web.views.test_networth import texts
from ynab_unlinked.buckets import Bucket
from ynab_unlinked.config import LatestConfig, TrackedAccount
from ynab_unlinked.config.models.v2 import CurrencyFormat
from ynab_unlinked.core.finance import AccountMove, Flows, Period
from ynab_unlinked.formatter import Formatter
from ynab_unlinked.store import Store
from ynab_unlinked.web import theme
from ynab_unlinked.web.components.flow_chart import bridge_options, months_options
from ynab_unlinked.web.state import AppState
from ynab_unlinked.web.theme import palette_for
from ynab_unlinked.web.views.networth import flows
from ynab_unlinked.ynab_api import Client

pytestmark = pytest.mark.version("V4")

BUDGET_ID = "00000000-0000-0000-0000-000000000001"
CHECKING = str(uuid.UUID(int=24))
FUND = str(uuid.UUID(int=21))
OLD = str(uuid.UUID(int=26))
FORMATTER = Formatter(
    date_format="DD/MM/YYYY",
    currency_format=CurrencyFormat(
        iso_code="EUR",
        decimal_digits=2,
        decimal_separator=".",
        symbol_first=False,
        group_separator=",",
        currency_symbol="€",
        display_symbol=True,
    ),
)


def ago(days: int) -> dt.date:
    return dt.date.today() - dt.timedelta(days=days)


# (account, days ago, milliunits, payee, transfer to)
ROWS = [
    (CHECKING, 400, 2_500_000, "Starting Balance", None),
    (FUND, 400, 40_000_000, "Starting Balance", None),
    (OLD, 400, 5_000_000, "Starting Balance", None),
    # Emptied into checking, then closed: still a transfer, not money from nowhere
    (OLD, 30, -5_000_000, "Transfer : Checking", CHECKING),
    (CHECKING, 30, 5_000_000, "Transfer : Old savings", OLD),
    (CHECKING, 20, 3_000_000, "Employer", None),
    (CHECKING, 18, -900_000, "Landlord", None),
    (CHECKING, 15, -1_000_000, "Transfer : Fund", FUND),
    (FUND, 15, 1_000_000, "Transfer : Checking", CHECKING),
    (FUND, 5, -400_000, "Reconciliation Balance Adjustment", None),
]


@pytest.fixture
def no_sync(mocker: MockerFixture) -> MagicMock:
    return mocker.patch.object(AppState, "sync_in_background")


@pytest.fixture
def synced(config_v4: LatestConfig, ynab_api: YnabClientStub, store_file: Path) -> Store:
    config_v4.accounts = [
        TrackedAccount(id=CHECKING, name="💶 Checking", type="checking", bucket=Bucket.CASH),
        TrackedAccount(id=FUND, name="📈 Fund", type="otherAsset", bucket=Bucket.ASSETS),
    ]
    config_v4.save()
    ynab_api.api("transactions").get_transactions.return_value = TransactionsResponse(
        data=TransactionsResponseData(
            transactions=[
                TransactionDetailFactory(
                    id=f"t{n}",
                    account_id=uuid.UUID(account),
                    var_date=ago(days),
                    amount=amount,
                    payee_name=payee,
                    transfer_account_id=None if to is None else uuid.UUID(to),
                )
                for n, (account, days, amount, payee, to) in enumerate(ROWS)
            ],
            server_knowledge=1,
        )
    )
    ynab_api.api("accounts").get_accounts.return_value = AccountsResponse(
        data=AccountsResponseData(
            accounts=[
                AccountFactory(id=uuid.UUID(CHECKING), name="💶 Checking", balance=8_600_000),
                AccountFactory(
                    id=uuid.UUID(FUND),
                    name="📈 Fund",
                    type="otherAsset",
                    on_budget=False,
                    balance=40_600_000,
                ),
                AccountFactory(
                    id=uuid.UUID(OLD), name="💰 Old savings", type="savings", closed=True, balance=0
                ),
            ],
            server_knowledge=1,
        )
    )
    store = Store(store_file)
    store.sync(Client("api-key"), BUDGET_ID)
    return store


async def open_months(user: User) -> None:
    await user.open("/networth?tab=months")
    await user.should_see(marker="period-panel", retries=20)


async def test_the_months_tab_splits_the_change_into_saving_and_assets(
    synced: Store, no_sync, user: User
):
    await open_months(user)

    assert texts(user, "tile-change").startswith("Change +1,700.00€")
    assert texts(user, "tile-saved").startswith("From saving +2,100.00€")
    assert texts(user, "tile-assets").startswith("From assets -400.00€")
    chart = user.find(marker="months-chart").elements.pop()
    names = [series["name"] for series in chart.options["series"]]
    # The transfer from the closed account moves nothing, so there is no Other
    assert names == ["month", "Saved", "Assets", "Net"]
    assert sum(point["value"] for point in chart.options["series"][3]["data"]) == pytest.approx(
        1_700
    )


async def test_the_panel_shows_the_whole_range_until_a_month_is_picked(
    synced: Store, no_sync, user: User
):
    await open_months(user)

    assert texts(user, "step-income") == "+3,000.00€"
    assert texts(user, "step-spending") == "-900.00€"
    assert texts(user, "step-net") == "+1,700.00€"
    assert "assets -400.00€" in texts(user, f"moved-{FUND}")
    assert texts(user, f"moved-{OLD}").startswith("💰 Old savings closed")
    assert texts(user, "came-in") == "Employer 3,000.00€"
    await user.should_not_see(marker="period-clear")
    await user.should_not_see(marker="period-title")


async def test_clicking_a_month_shows_it_and_clicking_it_again_shows_the_range(
    synced: Store, no_sync, user: User
):
    await open_months(user)
    chart = user.find(marker="months-chart")
    keys = chart.elements.copy().pop().options["xAxis"]["data"]
    month = keys.index(ago(5).strftime("%Y-%m"))

    chart.trigger("componentClick", {"componentType": "series", "dataIndex": month})

    await user.should_see(marker="period-clear", retries=20)
    assert texts(user, "period-title") == ago(5).strftime("%B %Y")

    # A click on the month's name under the bars picks it too: here, it goes back
    chart.trigger("componentClick", {"componentType": "xAxis", "value": keys[month]})

    await user.should_not_see(marker="period-clear", retries=20)
    await user.should_not_see(marker="period-title")


async def test_the_movers_tab_splits_each_account_into_your_money_and_assets(
    synced: Store, no_sync, user: User
):
    await user.open("/networth?tab=movers")
    await user.should_see(marker="movers", retries=20)

    assert texts(user, f"mover-{CHECKING}").split() == [
        "💶",
        "Checking",
        "+6,100.00€",
        "+6,100.00€",
        "—",
        "—",
    ]
    fund = texts(user, f"mover-{FUND}").split()
    assert fund[:5] == ["📈", "Fund", "+600.00€", "+1,000.00€", "-400.00€"]
    assert fund[5].startswith("−")
    assert texts(user, f"mover-{OLD}").split()[:5] == [
        "💰",
        "Old",
        "savings",
        "closed",
        "-5,000.00€",
    ]


async def test_tabs_switch_without_leaving_the_page(synced: Store, no_sync, user: User):
    await user.open("/networth")
    await user.should_see(marker="nw-figure", retries=20)

    user.find(marker="nw-tab-movers").click()
    await user.should_see(marker="movers", retries=20)
    user.find(marker="nw-tab-overview").click()
    await user.should_see(marker="nw-figure", retries=20)


@pytest.mark.parametrize(
    ("current", "clicked", "expected"),
    [(None, 3, 3), (3, 5, 5), (3, 3, None), (3, None, None)],
    ids=["first pick", "another month", "the same month again", "outside the bars"],
)
def test_next_selection(current, clicked, expected):
    assert flows.next_selection(current, clicked) == expected


@pytest.mark.parametrize(
    ("key", "expected"),
    [
        ("1M", dt.date(2026, 11, 1)),
        ("3M", dt.date(2026, 9, 1)),
        ("YTD", dt.date(2026, 1, 1)),
        ("1Y", dt.date(2025, 12, 1)),
        ("All", dt.date(2025, 3, 1)),
    ],
)
def test_a_range_covers_whole_months_up_to_today(key: str, expected: dt.date):
    today = dt.date(2026, 11, 9)

    assert flows.months_range(key, today, dt.date(2025, 3, 14)) == (expected, today)


def test_a_range_never_starts_before_the_month_of_the_first_transaction():
    today = dt.date(2026, 11, 9)

    assert flows.months_range("1Y", today, dt.date(2026, 7, 20))[0] == dt.date(2026, 7, 1)


def test_the_bridge_leaves_out_empty_steps_and_ends_with_the_net_change():
    steps = flows.bridge(Flows(income=10, spending=-4, transfers=0, outside=-1))

    assert [(step.label, step.amount) for step in steps] == [
        ("Income", 10),
        ("Spending", -4),
        ("Other", -1),
        ("Net", 5),
    ]


@pytest.mark.parametrize(
    ("part", "change", "expected"),
    [(80, 100, "80% of the change"), (150, 100, None), (-20, 100, None), (10, 0, None)],
    ids=["a share", "more than the change", "the other way", "no change"],
)
def test_share_of_change_only_when_it_reads_as_a_part(part, change, expected):
    assert flows.share_of_change(part, Flows(income=change)) == expected


def test_a_return_is_per_year_only_over_more_than_a_year():
    move = AccountMove("fund", 100, 121, Flows(assets=21), rate=0.21)

    assert flows.rate_text(move, 200) == "+21.0%"
    assert flows.rate_text(move, 730) == "+10.0%/yr"
    assert flows.rate_text(AccountMove("chk", 0, 5, Flows(income=5), None), 30) == "—"


def test_the_drawer_lists_only_accounts_that_moved():
    still = AccountMove("still", 10, 10, Flows(), None)
    moved = AccountMove("moved", 10, 30, Flows(income=20), None)
    period = Period(
        dt.date(2026, 4, 1), dt.date(2026, 4, 30), Flows(income=20), 20, 40, (), (moved, still)
    )

    assert flows.moved(period) == [moved]


def test_only_the_two_ends_of_a_month_bar_are_rounded():
    months = [
        (dt.date(2026, 4, 1), Flows(income=3_000, spending=-1_000, assets=500)),
        (dt.date(2026, 5, 1), Flows(income=3_000, spending=-1_000, assets=-800)),
    ]

    options = months_options(
        months, palette_for(theme.DEFAULT_THEME, True), FORMATTER.currency_format
    )

    saved, assets = (options["series"][i]["data"] for i in (1, 2))
    # April: saved at the bottom, assets on top
    assert saved[0]["itemStyle"]["borderRadius"] == [0, 0, 0, 0]
    assert assets[0]["itemStyle"]["borderRadius"] == [3, 3, 0, 0]
    # May: saved goes up, assets down, each with its own end
    assert saved[1]["itemStyle"]["borderRadius"] == [3, 3, 0, 0]
    assert assets[1]["itemStyle"]["borderRadius"] == [0, 0, 3, 3]


def test_the_waterfall_starts_each_step_where_the_last_one_ended_and_the_net_at_zero():
    steps = [
        (step.label, step.amount, step.kind)
        for step in flows.bridge(Flows(income=3_000_000, spending=-1_000_000, assets=-400_000))
    ]

    options = bridge_options(
        steps,
        ["a", "b", "c", "d"],
        palette_for(theme.DEFAULT_THEME, True),
        FORMATTER.currency_format,
    )

    assert [point["value"][1:] for point in options["series"][0]["data"]] == [
        [0, 3_000],
        [3_000, 2_000],
        [2_000, 1_600],
        [0, 1_600],
    ]


def test_spending_larger_than_income_takes_the_waterfall_below_zero():
    steps = [
        (step.label, step.amount, step.kind)
        for step in flows.bridge(Flows(income=4_600_000, spending=-11_100_000, assets=200_000))
    ]

    options = bridge_options(
        steps,
        ["a", "b", "c", "d"],
        palette_for(theme.DEFAULT_THEME, True),
        FORMATTER.currency_format,
    )

    assert [point["value"][1:] for point in options["series"][0]["data"]] == [
        [0, 4_600],
        [4_600, -6_500],
        [-6_500, -6_300],
        [0, -6_300],
    ]
