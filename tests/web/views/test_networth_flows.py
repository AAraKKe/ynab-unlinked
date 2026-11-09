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
from ynab_unlinked.web.state import AppState
from ynab_unlinked.web.views.networth import flows
from ynab_unlinked.ynab_api import Client

pytestmark = pytest.mark.version("V4")

BUDGET_ID = "00000000-0000-0000-0000-000000000001"
CHECKING = str(uuid.UUID(int=24))
FUND = str(uuid.UUID(int=21))
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
    balances = {CHECKING: 3_600_000, FUND: 40_600_000}
    ynab_api.api("accounts").get_accounts.return_value = AccountsResponse(
        data=AccountsResponseData(
            accounts=[
                AccountFactory(
                    id=uuid.UUID(CHECKING), name="💶 Checking", balance=balances[CHECKING]
                ),
                AccountFactory(
                    id=uuid.UUID(FUND),
                    name="📈 Fund",
                    type="otherAsset",
                    on_budget=False,
                    balance=balances[FUND],
                ),
            ],
            server_knowledge=1,
        )
    )
    store = Store(store_file)
    store.sync(Client("api-key"), BUDGET_ID)
    return store


async def test_the_months_tab_splits_the_change_into_saving_and_valuation(
    synced: Store, no_sync, user: User
):
    await user.open("/networth?tab=months")
    await user.should_see(marker="tile-change", retries=20)

    assert texts(user, "tile-change").startswith("Change +1,700.00€")
    assert texts(user, "tile-saved").startswith("From saving +2,100.00€")
    assert texts(user, "tile-valuation").startswith("From valuation -400.00€")
    chart = user.find(marker="months-chart").elements.pop()
    names = [series["name"] for series in chart.options["series"]]
    assert names == ["Saved", "Valuation", "Other", "Net"]
    assert sum(chart.options["series"][3]["data"]) == pytest.approx(1_700)


async def test_the_change_tile_opens_where_the_change_came_from(synced: Store, no_sync, user: User):
    await user.open("/networth?tab=months")
    await user.should_see(marker="tile-change", retries=20)

    user.find(marker="tile-change").click()

    await user.should_see(marker="period-drawer", retries=20)
    assert texts(user, "period-headline") == ("You saved 2,100.00€, but valuation took 400.00€.")
    assert texts(user, "step-income") == "+3,000.00€"
    assert texts(user, "step-spending") == "-900.00€"
    assert texts(user, "step-net") == "+1,700.00€"
    assert "transfers -1,000.00€" in texts(user, f"moved-{CHECKING}")
    assert "valuation -400.00€" in texts(user, f"moved-{FUND}")


async def test_the_movers_tab_splits_each_account_into_your_money_and_valuation(
    synced: Store, no_sync, user: User
):
    await user.open("/networth?tab=movers")
    await user.should_see(marker="movers", retries=20)

    assert texts(user, f"mover-{CHECKING}").split() == [
        "💶",
        "Checking",
        "+1,100.00€",
        "+1,100.00€",
        "—",
        "—",
    ]
    fund = texts(user, f"mover-{FUND}").split()
    assert fund[:5] == ["📈", "Fund", "+600.00€", "+1,000.00€", "-400.00€"]
    assert fund[5].startswith("−")


async def test_tabs_switch_without_leaving_the_page(synced: Store, no_sync, user: User):
    await user.open("/networth")
    await user.should_see(marker="nw-figure", retries=20)

    user.find(marker="nw-tab-movers").click()
    await user.should_see(marker="movers", retries=20)
    user.find(marker="nw-tab-overview").click()
    await user.should_see(marker="nw-figure", retries=20)


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


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        (Flows(income=3_000_000, spending=-1_000_000), "You saved 2,000.00€."),
        (
            Flows(income=1_000_000, spending=-1_500_000, valuation=800_000),
            "You spent 500.00€ more than came in, but valuation added 800.00€.",
        ),
        (
            Flows(income=1_000_000, valuation=200_000),
            "You saved 1,000.00€, and valuation added 200.00€.",
        ),
    ],
)
def test_the_headline_says_where_the_change_came_from(given: Flows, expected: str):
    assert flows.headline(given, FORMATTER) == expected


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
    move = AccountMove("fund", 100, 121, Flows(valuation=21), rate=0.21)

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
