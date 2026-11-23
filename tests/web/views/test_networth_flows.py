import datetime as dt
import uuid
from dataclasses import replace
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
from tests.web.views.test_networth import serve_note, texts, tooltip
from ynab_unlinked.buckets import Bucket
from ynab_unlinked.config import LatestConfig, TrackedAccount
from ynab_unlinked.config.models.v2 import CurrencyFormat
from ynab_unlinked.core.finance import AccountMove, Flows
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


@pytest.fixture
def noted(synced: Store, ynab_api: YnabClientStub) -> Store:
    """`synced`, with a note on the month running."""
    serve_note(ynab_api, synced, "Sold the car")
    return synced


def on(user: User, marker: str) -> bool:
    return "on" in user.find(marker=marker).elements.copy().pop().classes


def outlined(user: User) -> str:
    """The step of the waterfall drawn as picked."""
    options = user.find(marker="bridge").elements.copy().pop().options
    names = options["xAxis"]["data"]
    data = options["series"][0]["data"]
    (picked,) = [n for n, p in zip(names, data, strict=True) if p["itemStyle"].get("borderWidth")]
    return picked


async def open_months(user: User) -> None:
    await user.open("/networth?tab=months")
    await user.should_see(marker="period-panel", retries=20)


async def test_the_months_tab_splits_the_change_into_saving_and_assets(
    synced: Store, no_sync, user: User
):
    await open_months(user)

    assert texts(user, "tile-change").startswith("Change +1,700.00€")
    assert texts(user, "tile-saved").startswith("From saving +2,100.00€")
    assert texts(user, "tile-assets").startswith("From growth -400.00€")
    chart = user.find(marker="months-chart").elements.pop()
    names = [series["name"] for series in chart.options["series"]]
    # The transfer from the closed account moves nothing, so there is no Other
    assert names == ["month", "Saved", "Growth", "Net"]
    assert sum(point["value"] for point in chart.options["series"][3]["data"]) == pytest.approx(
        1_700
    )


async def test_a_month_says_its_note_also_once_one_is_picked(noted: Store, no_sync, user: User):
    await open_months(user)

    assert "Sold the car" in tooltip(user, "months-chart")

    # Picking a month draws the chart again, the others faded: the note stays
    user.find(marker="months-chart").trigger(
        "componentClick", {"componentType": "series", "dataIndex": 0}
    )
    await user.should_see(marker="period-clear", retries=20)
    assert "Sold the car" in tooltip(user, "months-chart")


async def test_the_panel_shows_the_whole_range_until_a_month_is_picked(
    synced: Store, no_sync, user: User
):
    await open_months(user)

    assert texts(user, "step-income") == "+3,000.00€"
    assert texts(user, "step-spending") == "-900.00€"
    assert texts(user, "step-net") == "+1,700.00€"
    await user.should_not_see(marker="period-clear")
    await user.should_not_see(marker="period-title")


async def test_the_panel_lists_income_by_payee_until_another_bar_is_picked(
    synced: Store, no_sync, user: User
):
    await open_months(user)

    assert on(user, "term-income")
    assert texts(user, "breakdown-row-0").split() == [
        "Employer",
        "into",
        "💶",
        "Checking",
        "+3,000.00€",
        "100%",
        "·",
        "1",
        "transaction",
    ]
    assert texts(user, "tx-head") == "1 transaction"
    assert texts(user, "tx-row").split()[-4:] == ["Employer", "💶", "Checking", "+3,000.00€"]
    assert outlined(user) == "Income"

    user.find(marker="term-assets").click()

    await user.should_see("1 value change", marker="tx-head")
    assert on(user, "term-assets") and not on(user, "term-income")
    fund = texts(user, "breakdown-row-0").split()
    assert fund[:2] == ["📈", "Fund"] and fund[3:5] == ["return", "-400.00€"]
    assert fund[-3:] == ["1", "value", "change"]
    assert outlined(user) == "Growth"


async def test_a_click_on_a_bar_of_the_waterfall_picks_it(synced: Store, no_sync, user: User):
    await open_months(user)
    chart = user.find(marker="bridge")
    names = chart.elements.copy().pop().options["xAxis"]["data"]

    chart.trigger("componentClick", {"componentType": "series", "dataIndex": names.index("Net")})
    chart.trigger(
        "componentClick", {"componentType": "series", "dataIndex": names.index("Spending")}
    )

    await user.should_see("Landlord", marker="tx-row")
    assert on(user, "term-spending")
    assert texts(user, "breakdown-total") == "-900.00€"


@pytest.fixture
def busy(synced: Store, ynab_api: YnabClientStub) -> Store:
    """`synced` with thirty days of groceries on top of the rent."""
    transactions = ynab_api.api("transactions").get_transactions.return_value.data.transactions
    transactions += [
        TransactionDetailFactory(
            id=f"g{n}",
            account_id=uuid.UUID(CHECKING),
            var_date=ago(n),
            amount=-50_000,
            payee_name="Market",
            category_id=uuid.UUID(int=300),
            category_name="Groceries",
        )
        for n in range(1, 31)
    ]
    synced.sync(Client("api-key"), BUDGET_ID)
    return synced


async def test_a_row_narrows_the_transactions_and_a_long_list_shows_more(
    busy: Store, no_sync, user: User
):
    await open_months(user)
    user.find(marker="term-spending").click()
    await user.should_see("31 transactions", marker="tx-head")
    assert len(user.find(marker="tx-row").elements) == flows.PAGE
    assert texts(user, "breakdown-row-0").startswith("Groceries -1,500.00€")

    user.find(marker="tx-more").click()

    await user.should_not_see(marker="tx-more")
    assert len(user.find(marker="tx-row").elements) == 31

    user.find(marker="breakdown-row-0").click()

    await user.should_see("30 transactions", marker="tx-head")
    assert on(user, "breakdown-row-0")
    # Narrowing starts the list over
    assert len(user.find(marker="tx-row").elements) == flows.PAGE
    assert texts(user, "tx-more") == f"Show {30 - flows.PAGE} more"

    user.find(marker="tx-all").click()

    await user.should_see("31 transactions", marker="tx-head")
    assert not on(user, "breakdown-row-0")
    user.find(marker="breakdown-row-1").click()
    await user.should_see("1 transaction", marker="tx-head")
    user.find(marker="breakdown-row-1").click()
    await user.should_see("31 transactions", marker="tx-head")


async def test_a_month_picked_keeps_the_term_and_lists_its_own_transactions(
    busy: Store, no_sync, user: User
):
    await open_months(user)
    user.find(marker="term-spending").click()
    await user.should_see("31 transactions", marker="tx-head")
    user.find(marker="breakdown-row-0").click()
    await user.should_see("30 transactions", marker="tx-head")
    chart = user.find(marker="months-chart")
    keys = chart.elements.copy().pop().options["xAxis"]["data"]
    month = ago(1).strftime("%Y-%m")
    # The groceries of that month and, when it falls in it, the rent
    in_month = sum(1 for days in [*range(1, 31), 18] if ago(days).strftime("%Y-%m") == month)

    chart.trigger("componentClick", {"componentType": "series", "dataIndex": keys.index(month)})

    await user.should_see(marker="period-clear")
    await user.should_see(flows.count_text("spending", in_month), marker="tx-head")
    assert on(user, "term-spending")
    await user.should_not_see(marker="tx-all")


async def test_the_i_of_the_waterfall_says_what_the_three_words_mean(
    synced: Store, no_sync, user: User
):
    await open_months(user)

    user.find(marker="terms-info").click()

    await user.should_see(marker="terms-dialog")
    assert texts(user, "term-meaning-income").startswith(
        "Income Money that arrived in your budget accounts from someone else"
    )
    assert "-240.00€" in texts(user, "refund-example")
    await user.should_see(marker="growth-story")
    assert len(user.find(marker="growth-steps").elements.pop().default_slot.children) == 4
    user.find(marker="terms-done").click()
    await user.should_not_see(marker="terms-dialog")


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


async def test_a_click_anywhere_else_goes_back_to_the_whole_range(
    synced: Store, no_sync, user: User
):
    await open_months(user)
    chart = user.find(marker="months-chart")
    chart.trigger("componentClick", {"componentType": "series", "dataIndex": 0})
    await user.should_see(marker="period-clear", retries=20)
    # The page reports the clicks that land outside the chart and the month's panel
    assert theme.KEEP_PROP in chart.elements.copy().pop().props

    user.find(marker="months-tab").trigger(theme.OUTSIDE_EVENT)

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
        "now",
        "8,600.00€",
        "+6,100.00€",
        "+6,100.00€",
        "—",
        "—",
    ]
    fund = texts(user, f"mover-{FUND}").split()
    assert fund[:7] == ["📈", "Fund", "now", "40,600.00€", "+600.00€", "+1,000.00€", "-400.00€"]
    assert fund[7].startswith("−")
    # It held money the whole range: no mark, no note about one
    assert not fund[7].endswith("*")
    await user.should_not_see(marker="part-note")
    assert texts(user, f"mover-{OLD}").split()[:5] == [
        "💰",
        "Old",
        "savings",
        "closed",
        "-5,000.00€",
    ]
    # Closed and empty: the pill says it, no "now 0.00€" under it
    await user.should_not_see(marker=f"held-{OLD}")


async def test_the_movers_header_reads_change_as_your_money_plus_growth(
    synced: Store, no_sync, user: User
):
    await user.open("/networth?tab=movers")
    await user.should_see(marker="movers-head", retries=20)

    head = user.find(marker="movers-head").elements.pop()
    assert texts(user, "movers-head").split()[:7] == [
        "Account",
        "Change",
        "=",
        "Your",
        "money",
        "+",
        "Growth",
    ]
    # The signs are drawn only; the sum is said once, for screen readers and on hover
    assert head.props["title"] == "Change = Your money + Growth"
    assert "Change = Your money + Growth" in texts(user, "movers-head")


@pytest.mark.parametrize(
    ("end", "balance", "closed", "expected"),
    [
        (dt.date(2026, 11, 22), 47_633_210, False, "now 47,633.21€"),
        (dt.date(2026, 10, 31), 47_633_210, False, "on 31 Oct: 47,633.21€"),
        (dt.date(2025, 12, 31), -915_620, False, "on 31 Dec 2025: -915.62€"),
        (dt.date(2026, 11, 22), 0, False, "now 0.00€"),
        (dt.date(2026, 11, 22), 0, True, None),
    ],
    ids=["range ends today", "ends earlier", "another year", "open and empty", "closed and empty"],
)
def test_what_an_account_held_at_the_end_of_the_range(end, balance, closed, expected):
    move = AccountMove(FUND, 1_000_000, balance, Flows(), None)

    held = flows.end_balance_text(move, end, dt.date(2026, 11, 22), FORMATTER, closed)

    assert held == expected


async def test_the_i_of_return_tells_how_it_and_growth_can_point_different_ways(
    synced: Store, no_sync, user: User
):
    await user.open("/networth?tab=movers")
    await user.should_see(marker="movers", retries=20)

    user.find(marker="return-info").click()
    await user.should_see(marker="return-story", retries=20)
    assert texts(user, "story-count") == "1 of 4"
    assert texts(user, "story-text") == "You put 1,000.00€ into an account."
    chart = user.find(marker="story-chart").elements.pop()
    # Only the steps reached are drawn
    assert chart.options["series"][0]["data"] == [1000.0, None, None, None]

    for _ in range(3):
        user.find(marker="story-next").click()
    await user.should_see(marker="story-end", retries=20)
    assert texts(user, "story-count") == "4 of 4"
    assert texts(user, "story-return") == "Return +20.0%"
    assert texts(user, "story-growth") == "Growth -1,500.00€"
    assert chart.options["series"][0]["data"] == [1000.0, 1500.0, 10000.0, 8000.0]
    assert chart.options["series"][1]["data"] == [1000.0, 1000.0, 9500.0, 9500.0]

    user.find(marker="story-back").click()
    await user.should_see("3 of 4", retries=20)
    await user.should_not_see(marker="story-end")
    user.find(marker="story-next").click()
    await user.should_see(marker="story-done", retries=20)
    user.find(marker="story-done").click()
    await user.should_not_see(marker="return-story", retries=20)


def test_the_story_of_return_adds_up():
    steps = flows.return_story(FORMATTER)

    # Each step's Return compounds the ones before; what was put in is never a gain
    assert [step.rate for step in steps] == [0, 0.5, 0.5, pytest.approx(1.5 * 0.8 - 1)]
    assert [step.growth for step in steps] == [0, 500_000, 500_000, -1_500_000]


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
    move = AccountMove("fund", 100, 121, Flows(assets=21), rate=0.21, rate_days=200)
    longer = AccountMove("fund", 100, 121, Flows(assets=21), rate=0.21, rate_days=730)

    assert flows.rate_text(move, 200) == "+21.0%"
    assert flows.rate_text(longer, 730) == "+10.0%/yr"
    assert flows.rate_text(AccountMove("chk", 0, 5, Flows(income=5), None), 30) == "—"
    assert flows.rate_title(move, 200) is None


def test_a_return_over_part_of_the_range_is_marked_and_says_how_much():
    move = AccountMove("rsu", 1_000, 3_000, Flows(assets=6), rate=0.328, rate_days=205)

    assert flows.rate_text(move, 315) == "+32.8%*"
    assert flows.rate_title(move, 315) == "Held money on 205 of the 315 days of the range"
    # Per year over the days it is measured on, not the range's
    assert flows.rate_text(replace(move, rate=0.21, rate_days=730), 1_000) == "+10.0%/yr*"


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

    assert [point["value"][1:3] for point in options["series"][0]["data"]] == [
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

    assert [point["value"][1:3] for point in options["series"][0]["data"]] == [
        [0, 4_600],
        [4_600, -6_500],
        [-6_500, -6_300],
        [0, -6_300],
    ]
