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
