"""Home's cards about the running month: the pulse against a usual month and where it went."""

import calendar
import datetime as dt

import pytest
from nicegui.testing.user import User
from ynab import TransactionsResponse, TransactionsResponseData

from tests.factories import TransactionDetailFactory
from tests.helpers.ynab_api import YnabClientStub
from tests.web.views.test_cashflow_spending import (  # noqa: F401 (fixtures)
    BUDGET_ID,
    CHECKING,
    GROCERIES,
    RENT,
    no_sync,
    synced,
)
from tests.web.views.test_networth import texts
from ynab_unlinked.config import LatestConfig
from ynab_unlinked.store import Store
from ynab_unlinked.web.views.home.pulse import (
    CategoryPulse,
    MonthPulse,
    load_pulse,
    pace_line,
    rate_text,
    runway_text,
)
from ynab_unlinked.ynab_api import Client

pytestmark = pytest.mark.version("V4")


def this_month(day: int) -> dt.date:
    return dt.date.today().replace(day=day)


@pytest.fixture
def running(synced: Store, ynab_api: YnabClientStub) -> Store:  # noqa: F811
    """The year of `synced` (3,000 in, 1,300 out a month, one 2,000 trip) plus this month so
    far: 500 in, rent paid, some groceries."""
    response = ynab_api.api("transactions").get_transactions.return_value
    rows = [
        (500_000, "Side job", None),
        (-1_000_000, "Landlord", RENT),
        (-120_000, "Market", GROCERIES),
        (-30_000, "Corner shop", None),
    ]
    ynab_api.api("transactions").get_transactions.return_value = TransactionsResponse(
        data=TransactionsResponseData(
            transactions=[
                *response.data.transactions,
                *(
                    TransactionDetailFactory(
                        id=f"now{n}",
                        account_id=CHECKING,
                        var_date=this_month(1),
                        amount=amount,
                        payee_name=payee,
                        category_id=category,
                    )
                    for n, (amount, payee, category) in enumerate(rows)
                ),
            ],
            server_knowledge=2,
        )
    )
    synced.clear(BUDGET_ID)
    synced.sync(Client("api-key"), BUDGET_ID)
    return synced


def test_the_pulse_reads_the_month_so_far_against_the_complete_months(
    running: Store, config_v4: LatestConfig
):
    today = dt.date.today()

    pulse = load_pulse(running, config_v4, today)

    assert (pulse.month, pulse.day) == (today.replace(day=1), today.day)
    assert pulse.days == calendar.monthrange(today.year, today.month)[1]
    assert (pulse.income, pulse.spending, pulse.saved) == (500_000, 1_150_000, -650_000)
    # 11 complete months: 3,000 in, 1,300 out, and the 2,000 trip in one of them
    assert pulse.months == 11
    assert pulse.usual_income == 3_000_000
    assert round(pulse.usual_spending) == round((11 * 1_300_000 + 2_000_000) / 11)
    assert pulse.savings_rate == pytest.approx(1 - (11 * 1_300_000 + 2_000_000) / 33_000_000)
    assert [(item.name, item.spent, round(item.usual)) for item in pulse.top] == [
        ("🏠 Rent", 1_000_000, 1_000_000),
        ("🛒 Groceries", 120_000, 300_000),
        ("Uncategorized", 30_000, 0),
    ]


def test_a_budget_in_its_first_month_has_nothing_usual_to_compare_with(
    config_v4: LatestConfig, store_file
):
    pulse = load_pulse(Store(store_file), config_v4, dt.date(2026, 2, 10))

    assert (pulse.income, pulse.spending, pulse.months) == (0, 0, 0)
    assert (pulse.spent_share, pulse.savings_rate, pulse.runway, pulse.top) == (
        None,
        None,
        None,
        [],
    )
    assert pace_line(pulse) == "No complete month yet to compare with."


def pulse(**changes: object) -> MonthPulse:
    values: dict[str, object] = {
        "month": dt.date(2026, 4, 1),
        "day": 10,
        "days": 30,
        "income": 0,
        "spending": 500_000,
        "usual_income": 3_000_000,
        "usual_spending": 1_000_000,
        "months": 11,
        "savings_rate": 0.4321,
        "runway": 6.04,
        "top": [CategoryPulse("rent", "Rent", 500_000, 500_000)],
    }
    return MonthPulse(**(values | changes))  # type: ignore[arg-type]


def test_the_pace_line_compares_spending_and_the_days_gone():
    assert pace_line(pulse()) == "50% of a usual month's spending, 33% of the month gone"
    assert pace_line(pulse(spending=1_300_000, day=30)) == (
        "130% of a usual month's spending, 100% of the month gone"
    )


def test_the_years_figures_are_worded_or_dashed():
    assert (rate_text(0.4321), runway_text(6.04)) == ("43.2%", "6.0 months")
    assert (rate_text(None), runway_text(None)) == ("—", "—")


async def test_home_shows_the_month_and_where_it_went(
    running: Store,
    no_sync,  # noqa: F811
    user: User,
):
    await user.open("/")
    await user.should_see(marker="month-pulse", retries=20)

    month = texts(user, "month-pulse")
    assert f"{dt.date.today():%B}" in month
    assert "Income 500.00€ Spending 1,150.00€ Net so far -650.00€" in month
    assert "of a usual month's spending" in texts(user, "month-pace")
    assert texts(user, "month-rate") == "50.6%"
    top = texts(user, "month-top")
    assert top.index("🏠 Rent") < top.index("🛒 Groceries") < top.index("Uncategorized")
    assert "1,000.00€" in top


async def test_a_category_of_the_month_opens_its_months_in_spending(
    running: Store,
    no_sync,  # noqa: F811
    user: User,
):
    await user.open("/")
    await user.should_see(marker="month-top", retries=20)

    user.find(marker=f"month-top-{GROCERIES}").click()

    await user.should_see(marker="category-detail")
    await user.should_see("Everyday / 🛒 Groceries")
