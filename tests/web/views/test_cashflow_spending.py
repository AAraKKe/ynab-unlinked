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
from tests.helpers.ynab_api import YnabClientStub
from tests.web.views.test_networth import texts
from ynab_unlinked.config import LatestConfig
from ynab_unlinked.core.cashflow import CashFlow, CategoryTrend, FlowMonth, Volatility
from ynab_unlinked.store import Store
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
    first = month_ago(11, 1).strftime("%b")
    assert texts(user, "detail-months").startswith(f"Bills · {first}")
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
    assert texts(user, "category-detail").startswith("🏝 Vacation Everyday")


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
