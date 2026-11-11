import datetime as dt
import uuid
from dataclasses import replace
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from nicegui import ui
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
from tests.helpers.ynab_api import YnabClientStub, month_response
from tests.web.views.test_networth import texts
from ynab_unlinked.config import LatestConfig
from ynab_unlinked.config.models.v2 import CurrencyFormat
from ynab_unlinked.core.plan import Assumptions, Fit, Goal, Position, Return
from ynab_unlinked.formatter import Formatter
from ynab_unlinked.store import Store
from ynab_unlinked.web.components.plan_chart import MEASURED, PLAN, SO_FAR
from ynab_unlinked.web.state import AppState
from ynab_unlinked.web.views.plan import data as plan
from ynab_unlinked.ynab_api import Client

pytestmark = pytest.mark.version("V4")

BUDGET_ID = "00000000-0000-0000-0000-000000000001"
CHECKING = uuid.UUID(int=24)
FUND = uuid.UUID(int=21)
RENT, GOAL = uuid.UUID(int=1101), uuid.UUID(int=1102)
TODAY = dt.date(2026, 11, 11)
FORMATTER = Formatter(
    "YYYY-MM-DD",
    CurrencyFormat(
        iso_code="EUR",
        decimal_digits=2,
        decimal_separator=".",
        symbol_first=False,
        group_separator=",",
        currency_symbol="€",
        display_symbol=True,
    ),
)


def month_ago(months: int, day: int = 1) -> dt.date:
    today = dt.date.today()
    index = today.year * 12 + today.month - 1 - months
    return dt.date(index // 12, index % 12 + 1, day)


@pytest.fixture
def no_sync(mocker: MockerFixture) -> MagicMock:
    return mocker.patch.object(AppState, "sync_in_background")


def serve(ynab_api: YnabClientStub, rows: list[tuple], *, goal: bool = True) -> None:
    """A budget with a checking account, a fund and, when `goal`, a category with a target
    that grew 200 a month."""
    balances = {CHECKING: 0, FUND: 0}
    for _, account, amount, *_ in rows:
        balances[account] += amount
    ynab_api.api("transactions").get_transactions.return_value = TransactionsResponse(
        data=TransactionsResponseData(
            transactions=[
                TransactionDetailFactory(
                    id=f"t{n}",
                    account_id=account,
                    var_date=day,
                    amount=amount,
                    payee_name=payee,
                    category_id=RENT if amount < 0 and transfer is None else None,
                    transfer_account_id=transfer,
                )
                for n, (day, account, amount, payee, transfer) in enumerate(rows)
            ],
            server_knowledge=1,
        )
    )
    ynab_api.api("accounts").get_accounts.return_value = AccountsResponse(
        data=AccountsResponseData(
            accounts=[
                AccountFactory(id=CHECKING, name="💶 Checking", balance=balances[CHECKING]),
                AccountFactory(
                    id=FUND,
                    name="📈 Fund",
                    type="otherAsset",
                    on_budget=False,
                    balance=balances[FUND],
                ),
            ],
            server_knowledge=1,
        )
    )
    target = {"goal_type": "TB", "goal_target": 10_000_000} if goal else {}
    ynab_api.api("categories").get_categories.return_value = CategoriesResponse(
        data=CategoriesResponseData(
            category_groups=[
                CategoryGroupFactory(
                    id=uuid.UUID(int=901),
                    name="Bills",
                    categories=[
                        CategoryFactory(id=RENT, name="🏠 Rent"),
                        CategoryFactory(id=GOAL, name="🏝 Trip", balance=4_000_000, **target),
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
                    month=month_ago(months),
                    income=0,
                    budgeted=0,
                    activity=0,
                    to_be_budgeted=0,
                    deleted=False,
                )
                for months in range(14)
            ],
            server_knowledge=1,
        )
    )
    this_month = month_ago(0)

    def held(_: str, month: dt.date):
        ago = (this_month.year - month.year) * 12 + this_month.month - month.month
        return month_response(
            month, [CategoryFactory(id=GOAL, balance=4_000_000 - 200_000 * ago, **target)]
        )

    ynab_api.api("months").get_plan_month.side_effect = held


def a_year(complete: int = 12) -> list[tuple]:
    """`complete` months alike: 3,000 in, 1,300 spent, 500 moved to the fund, which started
    with 10,000 the month before them and gained 600 on its own six months ago."""
    rows: list[tuple] = [
        (month_ago(complete + 1), FUND, 10_000_000, "Starting Balance", None),
        (month_ago(6, 20), FUND, 600_000, "Market", None),
    ]
    for months in range(1, complete + 1):
        rows += [
            (month_ago(months, 1), CHECKING, 3_000_000, "Employer", None),
            (month_ago(months, 3), CHECKING, -1_300_000, "Landlord", None),
            (month_ago(months, 5), CHECKING, -500_000, "Transfer : Fund", FUND),
            (month_ago(months, 5), FUND, 500_000, "Transfer : Checking", CHECKING),
        ]
    return rows


@pytest.fixture
def synced(config_v4: LatestConfig, ynab_api: YnabClientStub, store_file: Path) -> Store:
    serve(ynab_api, a_year())
    store = Store(store_file)
    store.sync(Client("api-key"), BUDGET_ID)
    return store


def slide(user: User, key: str, value: float) -> None:
    slider = user.find(marker=f"plan-{key}").elements.pop()
    assert isinstance(slider, ui.slider)
    with user.client:
        slider.value = value


def series(user: User, marker: str = "plan-chart") -> dict[str, dict]:
    chart = user.find(marker=marker).elements.pop()
    return {item["name"]: item for item in chart.options["series"] if item["name"]}


# ---- the page --------------------------------------------------------------------------------


async def test_the_plan_starts_from_what_the_last_year_measured(synced: Store, no_sync, user: User):
    await user.open("/plan")
    await user.should_see(marker="plan-saving", retries=20)

    assert texts(user, "plan-saving") == "Saved a month 1,700.00€ 57% of what comes in"
    assert texts(user, "plan-end").startswith("Net worth in 10 years")
    assert texts(user, "plan-end").endswith("31,000.00€ today")
    assert texts(user, "knob-income") == "Income 3,000.00€ measured 3,000.00€ a month"
    # 500 a month ended up in the fund, of the 1,700 saved
    assert texts(user, "knob-net_assets") == (
        "Ends up in assets 500.00€ · 29% of what you save · measured 500.00€ a month"
    )
    assert texts(user, "plan-stays") == (
        "Left in the budget: 1,700.00€ saved − 500.00€ into assets = 1,200.00€ a month"
    )
    # The goal grew 200 a month, of the 1,200 that stayed in the budget
    assert texts(user, "knob-to_goal") == (
        "Goes to the goal 17% · 200.00€ "
        "of the 1,200.00€ left in the budget · measured 200.00€ a month"
    )
    # How far it looks is always there; the returns only once their section is opened
    await user.should_see(marker="knob-years")
    await user.should_not_see(marker="knob-assets_return")
    assert texts(user, "plan-returns-summary") == "assets 5.0% · inflation 2.0%"
    # A year ago there was one month to go by: too little to check the plan against
    await user.should_not_see(marker="plan-check")
    assert texts(user, "plan-months").startswith("12 complete months")
    assert texts(user, "plan-goal").startswith("Goal reached")
    assert "🏝 Trip · 10,000.00€" in texts(user, "plan-goal")
    await user.should_not_see(marker="plan-reset")

    lines = series(user)
    assert lines[MEASURED]["lineStyle"]["opacity"] == 0
    # A year of month ends and today, then today and 120 months
    assert (len(lines[SO_FAR]["data"]), len(lines[PLAN]["data"])) == (13, 121)
    assert lines[SO_FAR]["data"][-1][1] == lines[PLAN]["data"][0][1] == 31_000.0


async def test_a_slider_draws_another_plan_against_what_was_measured(
    synced: Store, no_sync, user: User
):
    await user.open("/plan")
    await user.should_see(marker="plan-saving", retries=20)
    before = series(user)[PLAN]["data"][-1][1]

    slide(user, "income", 10)

    await user.should_see("2,000.00€", marker="plan-saving")
    assert texts(user, "knob-income").startswith("Income 3,300.00€ · +10%")
    assert "against what was measured" in texts(user, "plan-end")
    lines = series(user)
    assert lines[MEASURED]["lineStyle"]["opacity"] == 1
    assert lines[MEASURED]["data"][-1][1] == before < lines[PLAN]["data"][-1][1]

    user.find(marker="plan-reset").click()

    await user.should_see("1,700.00€", marker="plan-saving")
    await user.should_not_see(marker="plan-reset")
    assert user.find(marker="plan-income").elements.pop().value == 0
    assert series(user)[MEASURED]["lineStyle"]["opacity"] == 0


async def test_what_was_moved_is_still_there_on_the_next_visit(synced: Store, no_sync, user: User):
    await user.open("/plan")
    await user.should_see(marker="plan-saving", retries=20)
    slide(user, "spending", -10)
    slide(user, "years", 5)
    await user.should_see("The next 5 years", marker="plan-title")

    await user.open("/plan")

    await user.should_see("The next 5 years", marker="plan-title", retries=20)
    assert texts(user, "knob-spending").startswith("Spending 1,170.00€ · −10%")
    assert len(series(user)[PLAN]["data"]) == 61


async def test_inflation_is_taken_out_of_todays_money(synced: Store, no_sync, user: User):
    await user.open("/plan")
    await user.should_see(marker="plan-saving", retries=20)
    today = series(user)[PLAN]["data"][-1][1]

    user.find(marker="money-future").click()

    await eventually(lambda: series(user)[PLAN]["data"][-1][1] != today)
    future = series(user)[PLAN]["data"][-1][1]
    # Ten years of prices rising 2% a year
    assert future / today == pytest.approx(1.02**10, rel=1e-4)


async def test_by_type_stacks_the_plan_in_assets_savings_and_cash(
    synced: Store, no_sync, user: User
):
    await user.open("/plan")
    await user.should_see(marker="plan-saving", retries=20)

    user.find(marker="grouping-type").click()

    await eventually(lambda: list(series(user)) == ["Assets", "Savings", "Cash"])
    stacked = series(user)
    # What was and what is planned in one run: 12 month ends, today and 120 months
    assert len(stacked["Assets"]["data"]) == 133
    assert stacked["Assets"]["data"][12][1] == 16_600.0
    assert stacked["Cash"]["data"][12][1] == 14_400.0


async def test_fewer_months_measured_draw_the_plan_again(synced: Store, no_sync, user: User):
    await user.open("/plan")
    await user.should_see(marker="plan-saving", retries=20)

    user.find(marker="window-6M").click()

    await user.should_see("6 complete months", marker="plan-months", retries=20)
    assert len(series(user)[SO_FAR]["data"]) == 7


async def test_the_goal_is_drawn_to_its_target_and_a_year_past_it(
    synced: Store, no_sync, user: User
):
    await user.open("/plan")
    await user.should_see(marker="plan-goal-card", retries=20)

    assert texts(user, "plan-goal-card") == "🏝 Trip 4,000.00€ of 10,000.00€ · 40%"
    lines = series(user, "plan-goal-chart")
    # Twelve months ago, at 200 a month
    assert lines[SO_FAR]["data"][0][1] == 1_600.0
    assert lines[PLAN]["data"][-1][1] == 10_000.0
    assert lines[PLAN]["markLine"]["data"] == [{"yAxis": 10_000.0}]
    assert len(lines[PLAN]["data"]) < 121


async def test_the_returns_open_on_a_click_and_say_where_the_figure_comes_from(
    synced: Store, no_sync, user: User
):
    await user.open("/plan")
    await user.should_see(marker="plan-returns", retries=20)

    user.find(marker="plan-returns").click()

    await user.should_see(marker="knob-assets_return")
    # A year of months is too short to go by what the fund did in it
    assert texts(user, "knob-assets_return").endswith("5.0% a default: too little measured")
    assert "A return needs at least 3 years" in texts(user, "plan-assets_return-info-note")
    await user.should_see(marker="knob-inflation")

    # Open is how it is found on the next visit
    await user.open("/plan")
    await user.should_see(marker="knob-assets_return", retries=20)


async def test_what_comes_after_the_goal_is_two_switches_off_until_flipped(
    synced: Store, no_sync, user: User
):
    await user.open("/plan")
    await user.should_see(marker="plan-after", retries=20)
    assert texts(user, "plan-after-summary") == "nothing changes"
    await user.should_not_see(marker="plan-goal_spent")
    before = series(user)[PLAN]["data"][-1][1]

    user.find(marker="plan-after").click()
    await user.should_see(marker="plan-goal_spent")
    user.find(marker="plan-goal_spent").click()

    await eventually(lambda: texts(user, "plan-after-summary") == "spent")
    assert "10,000.00€ leaves net worth. Its share stays" in texts(user, "plan-after-note")
    # The 10,000 it was saved for are gone, in the money of ten years of prices at 2%
    assert before - series(user)[PLAN]["data"][-1][1] == pytest.approx(10_000 / 1.02**10, rel=1e-3)
    # Its line ends where it is reached: after that there is nothing to hold
    assert series(user, "plan-goal-chart")[PLAN]["data"][-1][1] == 10_000.0

    user.find(marker="plan-goal_to_assets").click()

    await eventually(lambda: texts(user, "plan-after-summary") == "spent · share to assets")
    assert "a month goes to assets" in texts(user, "plan-after-note")

    # Putting everything back turns both off again
    user.find(marker="plan-reset").click()

    await eventually(lambda: texts(user, "plan-after-summary") == "nothing changes")
    assert user.find(marker="plan-goal_spent").elements.pop().props["aria-checked"] == "false"
    assert series(user)[PLAN]["data"][-1][1] == before


async def test_a_budget_without_a_target_plans_net_worth_alone(
    config_v4: LatestConfig, ynab_api: YnabClientStub, store_file: Path, no_sync, user: User
):
    serve(ynab_api, a_year(), goal=False)
    Store(store_file).sync(Client("api-key"), BUDGET_ID)

    await user.open("/plan")
    await user.should_see(marker="plan-saving", retries=20)

    assert texts(user, "plan-goal") == ("Goal reached — add a balance target to a category in YNAB")
    await user.should_not_see(marker="knob-to_goal")
    await user.should_not_see(marker="plan-after")
    await user.should_not_see(marker="plan-goal-card")
    # No savings account either: its interest has nothing to grow
    await user.should_not_see(marker="knob-savings_return")


async def test_a_budget_in_its_first_month_has_nothing_to_measure(
    config_v4: LatestConfig, ynab_api: YnabClientStub, store_file: Path, no_sync, user: User
):
    serve(ynab_api, [(dt.date.today(), CHECKING, 3_000_000, "Employer", None)])
    Store(store_file).sync(Client("api-key"), BUDGET_ID)

    await user.open("/plan")

    await user.should_see(marker="plan-empty", retries=20)
    await user.should_not_see(marker="plan-knobs")


async def test_a_slider_goes_back_alone_and_shows_where_it_started(
    synced: Store, no_sync, user: User
):
    await user.open("/plan")
    await user.should_see(marker="plan-saving", retries=20)
    await user.should_not_see(marker="plan-income-reset")
    # Income starts in the middle of its slider: the mark its track is drawn around
    assert user.find(marker="plan-income").elements.pop().style["--mark"] == "50.00"

    slide(user, "income", 10)
    slide(user, "years", 5)

    await user.should_see(marker="plan-income-reset")
    await user.should_see(marker="plan-years-reset")
    await user.should_not_see(marker="plan-spending-reset")

    user.find(marker="plan-income-reset").click()

    await user.should_not_see(marker="plan-income-reset")
    await user.should_see("1,700.00€", marker="plan-saving")
    assert user.find(marker="plan-income").elements.pop().value == 0
    # The other one stays where it was put
    await user.should_see("The next 5 years", marker="plan-title")
    await user.should_see(marker="plan-years-reset")


async def test_what_ends_up_in_assets_is_what_went_in_less_what_came_out(
    config_v4: LatestConfig, ynab_api: YnabClientStub, store_file: Path, no_sync, user: User
):
    sale = [
        (month_ago(3, 12), FUND, -1_200_000, "Transfer : Checking", CHECKING),
        (month_ago(3, 12), CHECKING, 1_200_000, "Transfer : Fund", FUND),
    ]
    serve(ynab_api, a_year() + sale)
    Store(store_file).sync(Client("api-key"), BUDGET_ID)

    await user.open("/plan")
    await user.should_see(marker="plan-saving", retries=20)

    # 500 a month went in and 100 came out: 400 ended up there, of the 1,700 saved
    assert texts(user, "knob-net_assets") == (
        "Ends up in assets 400.00€ · 24% "
        "of what you save · measured 500.00€ in, 100.00€ out a month"
    )
    assert texts(user, "plan-stays") == (
        "Left in the budget: 1,700.00€ saved − 400.00€ into assets = 1,300.00€ a month"
    )

    # Selling more than is put in: assets give money back to the budget
    slide(user, "net_assets", -10)

    await user.should_see("-300.00€", marker="plan-net_assets-value")
    assert texts(user, "knob-net_assets").endswith(
        "assets give back · measured 500.00€ in, 100.00€ out a month"
    )
    assert texts(user, "plan-stays") == (
        "Left in the budget: 1,700.00€ saved + 300.00€ out of assets = 2,000.00€ a month"
    )
    assert "of the 2,000.00€ left in the budget" in texts(user, "knob-to_goal")

    # No more can end up in assets than is saved: the slider ends there
    slide(user, "net_assets", 70)

    await user.should_see("1,700.00€ · 100%", marker="plan-net_assets-value")
    slider = user.find(marker="plan-net_assets").elements.pop()
    assert slider.props["max"] == slider.value == pytest.approx(1_700 / 3_000 * 100)
    assert texts(user, "plan-stays") == (
        "Left in the budget: 1,700.00€ saved − 1,700.00€ into assets = 0.00€ a month"
    )
    assert texts(user, "knob-to_goal").startswith("Goes to the goal 15% · 0.00€")

    # Spending more leaves less to save, and what goes to assets follows it down
    slide(user, "spending", 50)

    await user.should_see("1,050.00€ · 100%", marker="plan-net_assets-value")


async def test_a_budget_that_repeats_itself_is_checked_against_its_last_year(
    config_v4: LatestConfig, ynab_api: YnabClientStub, store_file: Path, no_sync, user: User
):
    serve(ynab_api, a_year(26))
    store = Store(store_file)
    store.sync(Client("api-key"), BUDGET_ID)

    check = plan.load(store, config_v4, "1Y", dt.date.today()).check

    assert check is not None
    assert (check.since, check.until) == (
        month_ago(12) - dt.timedelta(days=1),
        month_ago(0) - dt.timedelta(days=1),
    )
    # 26 months of 1,200 in checking; the fund's 10,000, 26 of 500 and the 600 it gained
    assert check.was == 54_800_000
    # Twelve months alike were measured: only what the fund did and a year of prices
    # are off
    assert check.off is not None and abs(check.off) < 0.02

    await user.open("/plan")
    await user.should_see(marker="plan-check", retries=20)
    assert texts(user, "plan-check").endswith("It was 54,800.00€, 1.1% less.")


# ---- the data --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("window", "earliest", "expected"),
    [
        ("1Y", dt.date(2022, 1, 3), (dt.date(2025, 11, 1), dt.date(2026, 10, 31))),
        ("6M", dt.date(2022, 1, 3), (dt.date(2026, 5, 1), dt.date(2026, 10, 31))),
        ("All", dt.date(2022, 1, 3), (dt.date(2022, 1, 1), dt.date(2026, 10, 31))),
        ("3Y", dt.date(2026, 8, 20), (dt.date(2026, 8, 1), dt.date(2026, 10, 31))),
        ("1Y", dt.date(2026, 11, 2), None),
        ("nonsense", dt.date(2022, 1, 3), (dt.date(2025, 11, 1), dt.date(2026, 10, 31))),
    ],
    ids=["a year", "six months", "all", "a young budget", "its first month", "an unknown window"],
)
def test_a_window_is_whole_months_before_the_one_running(
    window: str, earliest: dt.date, expected: tuple[dt.date, dt.date] | None
):
    assert plan.window_months(window, TODAY, earliest) == expected


def found(*, assets_return: float | None = 0.061, months: int = 36, **changes: float) -> Fit:
    """`months` that earned 4,000 and spent 3,000 a month: 600 into assets (15% of what came
    in), the 400 left to the goal."""
    measured = None if assets_return is None else Return(assets_return, months / 12)
    base = Assumptions(
        income=4_000_000,
        spending=3_000_000,
        to_assets=0.15,
        to_savings=0.3,
        to_goal=1,
        assets_return=assets_return if assets_return is not None and months >= 36 else 0.05,
    )
    return Fit(
        start=dt.date(2025, 11, 1),
        end=dt.date(2026, 10, 31),
        months=months,
        assumptions=replace(base, **changes),
        assets_return=measured,
        savings_return=None,
        goal_pace=400_000,
        put_in=600_000,
        taken_out=changes.get("from_assets", 0),
    )


def page(fit: Fit | None = None, goal: Goal | None = None) -> plan.PlanPage:
    return plan.PlanPage(TODAY, Position(10_000_000, 20_000_000, 30_000_000), fit or found(), goal)


def test_the_sliders_start_exactly_on_what_was_measured_and_snap_once_moved():
    start = plan.measured(found(to_assets=0.1049, assets_return=0.0614, to_goal=0.4))

    assert (start.income, start.spending) == (0, 0)
    assert (start.net_assets, start.to_goal) == pytest.approx((10.49, 40))
    assert (start.assets_return, start.inflation, start.years) == pytest.approx((6.14, 2, 10))

    moved = plan.with_changes(start, {"net_assets": 13.333, "assets_return": 7.26})

    assert (moved.net_assets, moved.assets_return) == (13.3, 7.3)


def test_assets_that_gave_money_back_start_below_nothing():
    # 400 a month came out of them, of the 4,000 that come in
    knobs = plan.measured(found(to_assets=0, from_assets=400_000))

    assert knobs.net_assets == pytest.approx(-10)


@pytest.mark.parametrize(
    ("measured", "months", "start", "hint", "note"),
    [
        (
            0.061,
            36,
            6.1,
            "measured over the last 3.0 years",
            "Your assets returned 6.1% a year over the 3.0 years measured",
        ),
        (
            0.256,
            58,
            15,
            "measured over the last 4.8 years",
            "The slider ends at 15%, so the plan starts there.",
        ),
        (
            0.25,
            12,
            5,
            "a default: too little measured",
            "A return needs at least 3 years to say something, and the months measured cover "
            "1 year.",
        ),
        (
            None,
            36,
            5,
            "a default: too little measured",
            "5% a year is a default: none of your assets moved on its own",
        ),
    ],
    ids=["three years", "years too good to last", "one good year", "nothing moved"],
)
def test_the_assets_return_is_the_measured_one_over_enough_months_or_a_default(
    measured: float | None, months: int, start: float, hint: str, note: str
):
    fit = found(assets_return=measured, months=months)
    built = plan.build(page(fit), fit, {})

    assert built.knobs.assets_return == pytest.approx(start)
    assert plan.knob_hint("assets_return", page(fit), fit, built, FORMATTER) == hint
    assert note in " ".join(plan.return_note(fit))


def test_no_more_ends_up_in_assets_than_is_saved():
    fit = found()

    # A quarter of what comes in is saved
    assert plan.ceiling(fit, plan.measured(fit)) == 25
    assert plan.ceiling(fit, replace(plan.measured(fit), spending=20)) == pytest.approx(10)
    assert plan.ceiling(fit, replace(plan.measured(fit), spending=50)) == 0
    assert plan.build(page(fit), fit, {"net_assets": 40}).knobs.net_assets == 25
    # Savings moved into assets over the months: more went in than was saved
    assert plan.measured(found(to_assets=0.6)).net_assets == 25


def test_the_mark_follows_a_slider_that_ends_sooner():
    knob = next(knob for knob in plan.KNOBS if knob.key == "net_assets")

    # From 50 below nothing to 25: a start at 10 sits four fifths of the way
    assert plan.mark(knob, 10, high=25) == 80


@pytest.mark.parametrize(
    ("key", "value", "expected"),
    [("income", 0, 50), ("to_goal", 54, 54), ("years", 10, 23.08), ("assets_return", 40, 100)],
    ids=["no change is the middle", "a share", "years", "past the end"],
)
def test_where_a_value_sits_along_its_slider(key: str, value: float, expected: float):
    knob = next(knob for knob in plan.KNOBS if knob.key == key)

    assert plan.mark(knob, value) == pytest.approx(expected, abs=0.01)


def test_only_sliders_that_were_moved_are_kept_and_junk_is_ignored():
    start = plan.measured(found())

    knobs = plan.with_changes(
        start,
        {
            "income": 12.4,
            "years": 400,
            "inflation": "3",
            "nonsense": 1,
            "spending": True,
            "goal_spent": True,
            "goal_to_assets": "yes",
        },
    )

    # A switch is on or off, a slider a number: anything else is left where it started
    assert plan.moved(knobs, start) == {"income": 12, "years": 40, "goal_spent": True}
    assert knobs.changed(start)


@pytest.mark.parametrize(
    ("goal", "changes", "summary", "note"),
    [
        (
            Goal("Trip", 7_000_000, 9_000_000),
            {},
            "nothing changes",
            "Its money stays where it is, and its share stays in savings and cash.",
        ),
        (
            Goal("Trip", 7_000_000, 9_000_000),
            {"goal_spent": True},
            "spent",
            "Once it is reached in Apr 2027: 9,000.00€ leaves net worth. Its share stays in "
            "savings and cash.",
        ),
        (
            Goal("Trip", 7_000_000, 9_000_000),
            {"goal_to_assets": True},
            "share to assets",
            "Once it is reached in Apr 2027: 400.00€ a month goes to assets. Its money stays "
            "where it is.",
        ),
        (
            Goal("Trip", 9_500_000, 9_000_000),
            {"goal_spent": True, "goal_to_assets": True},
            "spent · share to assets",
            "Now that it is reached: 9,500.00€ leaves net worth, and 400.00€ a month goes to "
            "assets.",
        ),
        (
            Goal("Trip", 0, 900_000_000),
            {"years": 3, "goal_spent": True},
            "spent",
            "Not reached in 3 years: nothing happens yet.",
        ),
    ],
    ids=["both off", "spent", "its share invested", "both, already reached", "too far"],
)
def test_what_comes_after_the_goal_is_said_in_the_plans_own_figures(
    goal: Goal, changes: dict[str, object], summary: str, note: str
):
    where = page(goal=goal)
    built = plan.build(where, found(), changes)

    assert plan.after_summary(built) == summary
    assert plan.after_note(where, built, FORMATTER) == note


def test_the_sliders_change_what_a_month_looks_like():
    fit = found()

    yours = plan.assumptions(fit, replace(plan.measured(fit), net_assets=20, income=10, to_goal=25))

    assert (yours.income, yours.to_assets, yours.from_assets) == (4_400_000, 0.2, 0)
    # What stays goes to savings and cash as it was measured, whatever the assets take
    assert yours.to_savings == 0.3
    # 1,400 saved, 880 of what came in into assets: the goal's quarter is of 520
    assert yours.stays * yours.to_goal == pytest.approx(130_000)

    gives = plan.assumptions(fit, replace(plan.measured(fit), net_assets=-10, income=10))

    # Below nothing assets give back: a tenth of what comes in, on top of what is saved
    assert (gives.to_assets, gives.from_assets) == (0, pytest.approx(440_000))
    assert gives.stays == pytest.approx(1_840_000)


@pytest.mark.parametrize(
    ("said", "was", "verdict"),
    [
        (100_000_000, 104_900_000, "It was 104,900.00€, 4.9% more."),
        (100_000_000, 88_000_000, "It was 88,000.00€, 12.0% less."),
        (100_000_000, 100_300_000, "It was 100,300.00€, about that."),
    ],
    ids=["it did better", "it did worse", "close enough"],
)
def test_the_check_says_what_the_plan_of_a_year_ago_said_and_what_happened(
    said: int, was: int, verdict: str
):
    check = plan.Check(dt.date(2025, 10, 31), dt.date(2026, 10, 31), said, was)

    assert plan.check_note(check, FORMATTER) == (
        "Checked against your past: measured up to Oct 2025, this plan said 100,000.00€ "
        f"for Oct 2026. {verdict}"
    )


def test_inflation_and_how_far_it_looks_do_not_make_another_plan():
    start = plan.measured(found())

    assert not replace(start, inflation=4, years=30).changed(start)
    assert replace(start, spending=-5).changed(start)


@pytest.mark.parametrize(
    ("goal", "changes", "value", "hint"),
    [
        (None, {}, "—", "add a balance target to a category in YNAB"),
        (Goal("Trip", 9_000_000, 9_000_000), {}, "reached", "Trip · 9,000.00€"),
        # 400 a month for 2,000: five months, a little faster with prices rising
        (Goal("Trip", 7_000_000, 9_000_000), {}, "Apr 2027", "Trip · 9,000.00€"),
        (
            Goal("Trip", 7_000_000, 9_000_000, dt.date(2027, 6, 1)),
            {},
            "Apr 2027",
            "Trip · 9,000.00€ · 2 months early",
        ),
        (
            Goal("Trip", 7_000_000, 9_000_000, dt.date(2027, 1, 31)),
            {},
            "Apr 2027",
            "Trip · 9,000.00€ · 3 months late",
        ),
        (
            Goal("Trip", 7_000_000, 9_000_000, dt.date(2027, 4, 30)),
            {},
            "Apr 2027",
            "Trip · 9,000.00€ · on its date",
        ),
        (Goal("Trip", 0, 900_000_000), {"years": 3}, "not in 3 years", "Trip · 900,000.00€"),
    ],
    ids=[
        "no goal",
        "it holds its target",
        "a target without a date",
        "before its date",
        "after its date",
        "on its date",
        "too far",
    ],
)
def test_the_goals_tile_says_when_and_against_its_date(
    goal: Goal | None, changes: dict[str, object], value: str, hint: str
):
    where = page(goal=goal)
    built = plan.build(where, found(), changes)

    assert plan.goal_value(where, built) == value
    assert plan.goal_hint(where, built, FORMATTER) == hint


def test_the_goals_chart_looks_a_year_past_the_slower_plan():
    where = page(goal=Goal("Trip", 7_000_000, 9_000_000))
    fit = found()

    # Five months as measured; with a quarter of what stays going to it, 20
    assert plan.goal_months(plan.build(where, fit, {})) == 17
    assert plan.goal_months(plan.build(where, fit, {"to_goal": 25})) == 32
    # A plan that never gets there shows all of it
    assert plan.goal_months(plan.build(where, fit, {"to_goal": 0})) == 120


def test_a_timeline_joins_what_was_with_what_is_planned():
    where = replace(
        page(),
        past=(plan.Past(dt.date(2026, 9, 30), 1, 2, 3), plan.Past(dt.date(2026, 10, 31), 1, 2, 4)),
    )
    line = plan.timeline(where, plan.build(where, found(), {"years": 1}).plan)

    assert line.days[:4] == (
        dt.date(2026, 9, 30),
        dt.date(2026, 10, 31),
        TODAY,
        dt.date(2026, 12, 11),
    )
    assert line.behind([6, 7, 8])[:4] == [6, 7, 8, None]
    assert line.ahead([8, 9])[:4] == [None, None, 8, 9]
    short = line.until(1)
    assert short.days[-1] == dt.date(2026, 12, 11)
    assert short.ahead([8, 9, 10]) == [None, None, 8, 9]


def test_the_end_is_compared_with_what_was_measured_once_the_plan_differs():
    where = page()
    same = plan.build(where, found(), {"years": 20})
    other = plan.build(where, found(), {"spending": -10})

    assert plan.end_hint(where, same, True, FORMATTER) == "60,000.00€ today"
    hint = plan.end_hint(where, other, True, FORMATTER)
    assert hint.startswith("+") and hint.endswith("against what was measured")
