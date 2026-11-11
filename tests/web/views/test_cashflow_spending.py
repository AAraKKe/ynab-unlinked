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
    CategoriesResponse,
    CategoriesResponseData,
    MonthSummariesResponse,
    MonthSummariesResponseData,
    MonthSummary,
    TransactionsResponse,
    TransactionsResponseData,
)

from tests.factories import (
    AccountFactory,
    CategoryFactory,
    CategoryGroupFactory,
    TransactionDetailFactory,
)
from tests.helpers.web import eventually
from tests.helpers.ynab_api import YnabClientStub
from tests.web.views.test_networth import texts
from ynab_unlinked.config import LatestConfig
from ynab_unlinked.core.cashflow import CashFlow, CategoryTrend, FlowMonth, Volatility
from ynab_unlinked.store import Store
from ynab_unlinked.web import theme
from ynab_unlinked.web.components.cashflow_chart import WORD_OPACITY, word_color
from ynab_unlinked.web.state import AppState
from ynab_unlinked.web.views.cashflow import data as cashflow
from ynab_unlinked.web.views.spending import data as spending
from ynab_unlinked.ynab_api import Client

pytestmark = pytest.mark.version("V4")

BUDGET_ID = "00000000-0000-0000-0000-000000000001"
CHECKING = uuid.UUID(int=24)
RENT, GROCERIES, TRIP = (uuid.UUID(int=n) for n in (1101, 1102, 1103))


def month_ago(months: int, day: int) -> dt.date:
    today = dt.date.today()
    index = today.year * 12 + today.month - 1 - months
    return dt.date(index // 12, index % 12 + 1, day)


@pytest.fixture
def no_sync(mocker: MockerFixture) -> MagicMock:
    return mocker.patch.object(AppState, "sync_in_background")


@pytest.fixture
def synced(config_v4: LatestConfig, ynab_api: YnabClientStub, store_file: Path) -> Store:
    rows = []
    for months in range(1, 13):
        rows += [
            (month_ago(months, 1), 3_000_000, "Employer", None),
            (month_ago(months, 3), -1_000_000, "Landlord", RENT),
            (month_ago(months, 10), -300_000, "Market", GROCERIES),
        ]
    rows.append((month_ago(4, 12), -2_000_000, "Airline", TRIP))
    ynab_api.api("transactions").get_transactions.return_value = TransactionsResponse(
        data=TransactionsResponseData(
            transactions=[
                TransactionDetailFactory(
                    id=f"t{n}",
                    account_id=CHECKING,
                    var_date=day,
                    amount=amount,
                    payee_name=payee,
                    category_id=category,
                )
                for n, (day, amount, payee, category) in enumerate(rows)
            ],
            server_knowledge=1,
        )
    )
    ynab_api.api("accounts").get_accounts.return_value = AccountsResponse(
        data=AccountsResponseData(
            accounts=[
                AccountFactory(id=CHECKING, name="💶 Checking", balance=sum(row[1] for row in rows))
            ],
            server_knowledge=1,
        )
    )
    ynab_api.api("categories").get_categories.return_value = CategoriesResponse(
        data=CategoriesResponseData(
            category_groups=[
                CategoryGroupFactory(
                    id=uuid.UUID(int=901),
                    name="Bills",
                    categories=[CategoryFactory(id=RENT, name="🏠 Rent")],
                ),
                CategoryGroupFactory(
                    id=uuid.UUID(int=902),
                    name="Everyday",
                    categories=[
                        CategoryFactory(id=GROCERIES, name="🛒 Groceries"),
                        CategoryFactory(id=TRIP, name="🏝 Vacation"),
                    ],
                ),
            ],
            server_knowledge=1,
        )
    )
    ynab_api.api("months").get_plan_months.return_value = MonthSummariesResponse(
        data=MonthSummariesResponseData(
            months=[
                MonthSummary(
                    month=month_ago(2, 1),
                    note="Moved flat",
                    income=0,
                    budgeted=0,
                    activity=0,
                    to_be_budgeted=0,
                    deleted=False,
                )
            ],
            server_knowledge=1,
        )
    )
    store = Store(store_file)
    store.sync(Client("api-key"), BUDGET_ID)
    return store


async def test_cash_flow_averages_the_complete_months(synced: Store, no_sync, user: User):
    await user.open("/cashflow")
    await user.should_see(marker="cf-income", retries=20)

    assert texts(user, "cf-income") == "Income a month 3,000.00€ median 3,000.00€"
    assert texts(user, "cf-spending").startswith("Spending a month 1,481.82€")
    # 11 complete months: 11 × 3,000 in, 11 × 1,300 + 2,000 out
    assert texts(user, "cf-rate").startswith("Savings rate 50.6%")
    chart = user.find(marker="cf-chart").elements.pop()
    # A label sits over the taller bar of its month
    income, spent = (chart.options["series"][i]["data"] for i in (0, 1))
    labels = [
        next((p["label"]["formatter"] for p in pair if p["label"]["show"]), None)
        for pair in zip(income, spent, strict=True)
    ]
    assert labels[-3] == "Moved flat"
    assert labels[-5] == "🏝 Vacation"
    assert texts(user, "cf-sources").startswith("Came in from by payee, the whole range Employer")


async def test_cash_flow_needs_a_complete_month(synced: Store, no_sync, user: User):
    await user.open("/cashflow")
    await user.should_see(marker="cf-income", retries=20)

    user.find(marker="range-1M").click()

    await user.should_see(marker="cf-empty", retries=20)


async def test_spending_lists_categories_with_how_they_move(synced: Store, no_sync, user: User):
    await user.open("/spending")
    await user.should_see(marker="sp-categories", retries=20)

    assert texts(user, f"category-{RENT}").startswith("🏠 Rent 1,000.00€")
    assert "steady" in texts(user, f"category-{RENT}")
    assert "not enough months" in texts(user, f"category-{TRIP}")
    assert texts(user, "group-Bills").startswith("Bills 1,000.00€")


def flow(
    trends: list[CategoryTrend], months: list[FlowMonth], liquid: int = 0
) -> cashflow.CashFlowPage:
    return cashflow.CashFlowPage(
        CashFlow(months[0].month, months[-1].month, tuple(months), tuple(trends)), None, liquid
    )


def trend(mean: float, label: str | None) -> CategoryTrend:
    return CategoryTrend("c", "C", "G", (int(mean),) * 3, Volatility(mean, 0.1, label, 3))


def test_runway_is_cash_and_savings_over_core_spending():
    months = [FlowMonth(dt.date(2026, m, 1), 3_000_000, 2_000_000, True) for m in range(1, 4)]
    page = flow([trend(1_500_000, "steady"), trend(500_000, "spiky")], months, liquid=6_000_000)

    assert cashflow.runway_text(page) == "4.0 months"


def test_a_savings_rate_compares_with_the_months_before():
    now = [FlowMonth(dt.date(2026, m, 1), 1_000, 600, True) for m in (5, 6)]
    before = [FlowMonth(dt.date(2026, m, 1), 1_000, 700, True) for m in (3, 4)]
    page = cashflow.CashFlowPage(
        CashFlow(now[0].month, now[-1].month, tuple(now)),
        CashFlow(before[0].month, before[-1].month, tuple(before)),
        0,
    )

    assert cashflow.rate_change(page) == "▲ 10.0 pts vs the 2 months before"


def test_a_sparkline_spans_its_box():
    points = spending.spark([0, 5, 10])

    assert points.split() == ["0.0,20.0", "36.0,11.0", "72.0,2.0"]


async def test_a_group_row_filters_and_a_second_click_shows_every_group(
    synced: Store, no_sync, user: User
):
    await user.open("/spending")
    await user.should_see(marker="sp-categories", retries=20)

    user.find(marker="group-Everyday").click()

    await user.should_not_see(marker=f"category-{RENT}", retries=20)
    await user.should_see(marker=f"category-{GROCERIES}")
    await user.should_see(marker=f"category-{TRIP}")

    user.find(marker="group-Everyday").click()

    await user.should_see(marker=f"category-{RENT}", retries=20)


async def test_the_group_dropdown_filters_the_table(synced: Store, no_sync, user: User):
    await user.open("/spending")
    await user.should_see(marker="sp-group-filter", retries=20)
    dropdown = user.find(marker="sp-group-filter").elements.pop()

    with user.client:
        dropdown.value = "Bills"

    await user.should_not_see(marker=f"category-{GROCERIES}", retries=20)
    await user.should_see(marker=f"category-{RENT}")


async def test_a_word_of_the_legend_filters_and_shows_again(synced: Store, no_sync, user: User):
    await user.open("/spending")
    await user.should_see(marker="sp-legend", retries=20)

    user.find(marker="word-steady").click()

    await user.should_not_see(marker=f"category-{TRIP}", retries=20)
    await user.should_see(marker=f"category-{RENT}")
    user.find(marker="sp-word-clear").click()
    await user.should_see(marker=f"category-{TRIP}", retries=20)


async def test_a_row_shows_its_category_in_the_charts_place_until_back(
    synced: Store, no_sync, user: User
):
    await user.open("/spending")
    await user.should_see(marker="sp-categories", retries=20)

    user.find(marker=f"category-{RENT}").click()

    await user.should_see(marker="category-detail", retries=20)
    await user.should_not_see(marker="sp-scatter")
    assert texts(user, "detail-title") == "Bills / 🏠 Rent"
    assert texts(user, "detail-stats").startswith("Average 1,000.00€ Median 1,000.00€")
    months = user.find(marker="detail-chart").elements.pop()
    assert months.options["series"][0]["data"] == [1_000.0] * 11

    # A new range keeps it open and updates it
    user.find(marker="range-6M").click()
    await user.should_see(marker="category-detail", retries=20)

    user.find(marker="detail-back").click()

    await user.should_see(marker="sp-scatter", retries=20)


async def test_a_dot_of_the_chart_opens_its_category(synced: Store, no_sync, user: User):
    await user.open("/spending")
    await user.should_see(marker="sp-scatter", retries=20)
    chart = user.find(marker="sp-scatter")
    dots = chart.elements.copy().pop().options["series"][0]["data"]
    vacation = [dot["label"]["formatter"] for dot in dots].index("🏝 Vacation")

    chart.trigger("componentClick", {"componentType": "series", "dataIndex": vacation})

    await user.should_see(marker="category-detail", retries=20)
    assert texts(user, "detail-title") == "Everyday / 🏝 Vacation"


async def test_a_filter_brings_the_chart_back_in_place_of_a_category(
    synced: Store, no_sync, user: User
):
    await user.open("/spending")
    await user.should_see(marker="sp-categories", retries=20)

    user.find(marker=f"category-{RENT}").click()
    await user.should_see(marker="category-detail", retries=20)
    user.find(marker="group-Everyday").click()

    await user.should_see(marker="sp-scatter", retries=20)
    await user.should_not_see(marker="category-detail")
    dots = user.find(marker="sp-scatter").elements.pop().options["series"][0]["data"]
    assert "🏠 Rent" not in [dot["label"]["formatter"] for dot in dots]

    user.find(marker=f"category-{GROCERIES}").click()
    await user.should_see(marker="category-detail", retries=20)
    user.find(marker="word-steady").click()

    await user.should_see(marker="sp-scatter", retries=20)
    await user.should_not_see(marker="category-detail")


def test_a_histogram_counts_months_in_equal_slices():
    bins = spending.histogram([0, 100, 100, 600], bins=3)

    assert [(b.low, b.high, b.months) for b in bins] == [(0, 200, 3), (200, 400, 0), (400, 600, 1)]


def test_a_group_mix_splits_its_spending_by_how_it_moves():
    trends = [
        CategoryTrend("a", "A", "Bills", (300,) * 6, Volatility(300, 0.1, "steady", 6)),
        CategoryTrend("b", "B", "Bills", (100,) * 6, Volatility(100, 1.0, "spiky", 6)),
        CategoryTrend("c", "C", "Fun", (50,) * 6, Volatility(50, None, None, 1)),
    ]
    page = CashFlow(dt.date(2026, 1, 1), dt.date(2026, 6, 30), (), tuple(trends))

    assert [(p.label, p.share) for p in spending.group_mix(page, "Bills")] == [
        ("steady", 0.75),
        ("spiky", 0.25),
    ]
    assert [p.label for p in spending.group_mix(page, "Fun")] == ["unrated"]


async def test_a_filter_redraws_only_the_table_and_the_chart(synced: Store, no_sync, user: User):
    await user.open("/spending")
    await user.should_see(marker="sp-legend", retries=20)
    tiles = user.find(marker="sp-total").elements.pop().id
    legend = user.find(marker="word-steady").elements.pop().id

    user.find(marker="word-steady").click()
    await user.should_not_see(marker=f"category-{TRIP}", retries=20)
    user.find(marker="group-Bills").click()
    await user.should_not_see(marker=f"category-{GROCERIES}", retries=20)

    # The page above the table is not drawn again, so the browser keeps its scroll
    assert user.find(marker="sp-total").elements.pop().id == tiles
    assert user.find(marker="word-steady").elements.pop().id == legend
    assert "on" in user.find(marker="word-steady").elements.pop().classes
    assert user.find(marker="sp-group-filter").elements.pop().value == "Bills"


# ---- the range and the links the pages share -------------------------------------------------


def on(user: User, marker: str) -> bool:
    return "on" in user.find(marker=marker).elements.pop().classes


async def test_a_range_picked_on_one_finance_page_is_the_range_of_the_others(
    synced: Store, no_sync, user: User
):
    await user.open("/cashflow")
    await user.should_see(marker="cf-income", retries=20)
    assert on(user, "range-1Y")

    user.find(marker="range-6M").click()
    await eventually(lambda: on(user, "range-6M"))

    await user.open("/spending")
    await user.should_see(marker="sp-scatter", retries=20)
    assert on(user, "range-6M")
    assert not on(user, "range-1Y")
    await user.open("/networth?tab=months")
    await user.should_see(marker="range-6M", retries=20)
    assert on(user, "range-6M")


async def test_a_link_to_a_category_opens_spending_on_its_months(
    synced: Store, no_sync, user: User
):
    await user.open(f"/spending?category={GROCERIES}")

    await user.should_see(marker="category-detail", retries=20)
    assert texts(user, "detail-title") == "Everyday / 🛒 Groceries"


async def test_a_link_to_a_category_the_range_does_not_have_opens_the_chart(
    synced: Store, no_sync, user: User
):
    await user.open("/spending?category=not-a-category")

    await user.should_see(marker="sp-scatter", retries=20)
    await user.should_not_see(marker="category-detail")


async def test_spending_shows_the_running_month_so_far(
    synced: Store, ynab_api: YnabClientStub, no_sync, user: User
):
    transactions = ynab_api.api("transactions").get_transactions.return_value.data.transactions
    transactions.append(
        TransactionDetailFactory(
            id="now",
            account_id=CHECKING,
            var_date=dt.date.today().replace(day=1),
            amount=-1_000_000,
            payee_name="Landlord",
            category_id=RENT,
        )
    )
    synced.clear(BUDGET_ID)
    synced.sync(Client("api-key"), BUDGET_ID)
    await user.open("/spending")
    await user.should_see(marker="sp-scatter", retries=20)

    user.find(marker="range-1M").click()

    await user.should_see(marker="sp-so-far", retries=20)
    assert texts(user, "sp-total") == "Spent so far 1,000.00€"
    # Eleven months of the same rent behind it: steady, though the range is one month
    assert "steady" in texts(user, f"category-{RENT}")


async def test_a_dot_of_the_scatter_is_in_the_colour_of_its_word(
    synced: Store, no_sync, user: User
):
    await user.open("/spending")
    await user.should_see(marker="sp-scatter", retries=20)

    palette = theme.DARK_PALETTE
    dots = user.find(marker="sp-scatter").elements.pop().options["series"][0]["data"]
    colours = {dot["label"]["formatter"]: dot["itemStyle"]["color"] for dot in dots}
    # Rent is the same every month; the one trip is a single purchase without a word
    assert colours["🏠 Rent"] == palette.good
    assert colours["🏝 Vacation"] == palette.text_3
    assert {dot["itemStyle"]["opacity"] for dot in dots} == {WORD_OPACITY}
    await user.should_see(marker="sp-dot-key")


def test_every_word_has_its_colour():
    palette = theme.LIGHT_PALETTE

    assert [word_color(label, palette) for label in ("steady", "variable", "spiky", "lumpy")] == [
        palette.good,
        palette.text_2,
        palette.warn,
        palette.accent_solid,
    ]
    assert word_color(None, palette) == palette.text_3


# ---- a lumpy category is about its charges, not about a month ----------------------------------


@pytest.mark.parametrize(
    ("every", "text"),
    [
        (12, "once a year"),
        (11.6, "once a year"),
        (6, "twice a year"),
        (24, "every two years"),
        (3, "every 3 months"),
        (1, "every month"),
        (0.2, "every month"),
    ],
)
def test_how_often_a_charge_comes_is_said_in_words(every: float, text: str):
    assert spending.every_text(every) == text


async def test_a_lumpy_category_shows_its_charges_and_what_to_set_aside(
    synced: Store, ynab_api: YnabClientStub, no_sync, user: User
):
    # A second trip six months before the first: the same price, twice a year
    transactions = ynab_api.api("transactions").get_transactions.return_value.data.transactions
    transactions.append(
        TransactionDetailFactory(
            id="trip-before",
            account_id=CHECKING,
            var_date=month_ago(10, 12),
            amount=-2_000_000,
            payee_name="Airline",
            category_id=TRIP,
        )
    )
    synced.clear(BUDGET_ID)
    synced.sync(Client("api-key"), BUDGET_ID)

    await user.open(f"/spending?category={TRIP}")
    await user.should_see(marker="category-detail", retries=20)

    assert texts(user, "detail-word") == "◆ lumpy"
    assert texts(user, "detail-figure") == "2,000.00€ a charge"
    assert texts(user, "detail-set-aside") == (
        "About twice a year. Set aside 333.33€ a month to have it ready."
    )
    last = month_ago(4, 1)
    assert texts(user, "detail-stats") == (
        f"A charge 2,000.00€ Charges 2 Comes twice a year Set aside 333.33€ Last one {last:%b %Y}"
    )
    chart = user.find(marker="detail-chart").elements.pop()
    assert [item["name"] for item in chart.options["legend"]["data"]] == [
        "Spent",
        "Set aside a month",
    ]
    # Its charges from the first one to now, the quiet months between them too
    months = user.find(marker="detail-chart").elements.pop().options["series"][0]["data"]
    assert months == [2_000.0, 0, 0, 0, 0, 0, 2_000.0, 0, 0, 0]
    await user.should_not_see(marker="detail-histogram")


async def test_a_category_spent_every_month_still_reads_a_month(synced: Store, no_sync, user: User):
    await user.open(f"/spending?category={RENT}")
    await user.should_see(marker="category-detail", retries=20)

    assert texts(user, "detail-figure") == "1,000.00€ a month"
    assert texts(user, "detail-set-aside") == (
        "About the same every month. Set aside 1,000.00€ a month and it is covered."
    )
    await user.should_see(marker="detail-histogram")


# ---- every kind of category is told in its own words ------------------------------------------


def euros(milliunits: int) -> str:
    return f"{milliunits / 1000:,.2f}€"


def told(label: str | None, spent: list[int], past: list[int] | None = None) -> spending.Story:
    """The story of a category that spent `spent` in the range's months (the last of the
    history `past`, which is the range when not given)."""
    past = spent if past is None else past
    history = tuple(month_ago(months, 1) for months in range(len(past), 0, -1))
    months = tuple(FlowMonth(month, 0, 0, True) for month in history[-len(spent) :])
    category = CategoryTrend(
        "c", "C", "G", tuple(spent), Volatility(0, 1.0, label, 0), past=tuple(past)
    )
    page = CashFlow(months[0].month, month_ago(0, 1), months, (category,), history=history)
    return spending.story(category, page, euros)


def test_a_steady_category_is_a_month_and_its_average_covers_it():
    story = told("steady", [1_000_000] * 6)

    assert story.figure == "1,000.00€ a month"
    assert story.guide == (
        "About the same every month.",
        "Set aside 1,000.00€ a month",
        "and it is covered.",
    )
    assert (story.section, story.line, story.histogram) == ("Each month", "Average", True)
    assert story.rows[0] == ("Average", "1,000.00€")


def test_a_variable_category_says_between_what_it_moves():
    story = told("variable", [200_000, 500_000, 300_000, 400_000, 600_000, 400_000])

    assert story.figure == "400.00€ a month"
    assert story.guide == (
        "Between 200.00€ and 600.00€ a month.",
        "Set aside 400.00€ a month",
        "to cover it over time.",
    )
    assert story.histogram


def test_a_lumpy_category_is_a_charge_over_its_history():
    # The range holds one charge; the history, three a year apart
    past = [171_000, *[0] * 11, 171_000, *[0] * 11, 171_000, 0]
    story = told("lumpy", past[-3:], past)

    assert story.figure == "171.00€ a charge"
    assert story.guide == (
        "About once a year.",
        "Set aside 14.25€ a month",
        "to have it ready.",
    )
    assert (story.section, story.line, story.line_value) == (
        "Each charge",
        "Set aside a month",
        14_250,
    )
    assert story.life.spent == tuple(past)
    assert [key for key, _ in story.rows] == [
        "A charge",
        "Charges",
        "Comes",
        "Set aside",
        "Last one",
    ]
    assert not story.histogram


def test_a_spiky_category_is_its_biggest_month_and_what_covers_months_like_it():
    # Nothing for a while, a small month, a big one, then quiet again
    past = [0, 0, 129_000, 0, 0, 0, 6_753_000, 0, 0, 0]
    story = told("spiky", past[-6:], past)

    assert story.figure == "up to 6,753.00€ a month"
    # 6,882 over the eight months since it first spent, the quiet ones after it too
    assert story.guide == (
        "Spent in 2 of the last 8 months.",
        "Set aside 860.25€ a month",
        "to cover months like these.",
    )
    assert story.life.spent == tuple(past[2:])
    assert story.rows == (
        ("Biggest month", "6,753.00€"),
        ("Months spent in", "2 of 8"),
        ("In all", "6,882.00€"),
        ("Set aside", "860.25€"),
        ("Last one", f"{month_ago(4, 1):%b %Y}"),
    )
    assert (story.line, story.histogram) == ("Set aside a month", False)


def test_something_bought_once_is_not_a_month():
    story = told(None, [0, 0, 2_000_000, 0, 0, 0])

    assert story.figure == "2,000.00€ once"
    assert story.guide == (
        f"Spent once, in {month_ago(4, 1):%b %Y}.",
        "",
        "Nothing to plan for yet.",
    )
    assert not story.histogram


def test_a_category_too_young_for_a_word_has_no_guide_yet():
    story = told(None, [300_000, 280_000])

    assert story.figure == "290.00€ a month"
    assert story.guide is None
