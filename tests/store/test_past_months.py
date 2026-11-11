import datetime as dt
import uuid
from pathlib import Path

import pytest
from freezegun import freeze_time
from ynab import (
    AccountsResponse,
    AccountsResponseData,
    MonthSummariesResponse,
    MonthSummariesResponseData,
    MonthSummary,
    TransactionsResponse,
    TransactionsResponseData,
)

from tests.factories import CategoryFactory
from tests.helpers.ynab_api import YnabClientStub, month_response
from ynab_unlinked.store import Store
from ynab_unlinked.store.store import PAST_MONTHS
from ynab_unlinked.ynab_api import Client

BUDGET_ID = "budget-1"
GOAL = uuid.UUID(int=11)
MARCH, APRIL, MAY, JUNE = (dt.date(2025, month, 1) for month in (3, 4, 5, 6))


@pytest.fixture
def store(tmp_path: Path) -> Store:
    return Store(tmp_path / "store.sqlite")


@pytest.fixture
def client(ynab_api: YnabClientStub) -> Client:
    return Client(api_key="an-api-key")


def serve(ynab_api: YnabClientStub, months: list[dt.date], held: dict[dt.date, int]) -> None:
    """A budget with these months, whose goal held `held` at the end of each."""
    ynab_api.api("transactions").get_transactions.return_value = TransactionsResponse(
        data=TransactionsResponseData(transactions=[], server_knowledge=1)
    )
    ynab_api.api("accounts").get_accounts.return_value = AccountsResponse(
        data=AccountsResponseData(accounts=[], server_knowledge=1)
    )
    ynab_api.api("months").get_plan_months.return_value = MonthSummariesResponse(
        data=MonthSummariesResponseData(
            months=[
                MonthSummary(
                    month=month, income=0, budgeted=0, activity=0, to_be_budgeted=0, deleted=False
                )
                for month in months
            ],
            server_knowledge=1,
        )
    )
    ynab_api.api("months").get_plan_month.side_effect = lambda _, month: month_response(
        month,
        [
            CategoryFactory(id=GOAL, balance=held.get(month, 0)),
            CategoryFactory(name="Gone", balance=5, deleted=True),
        ],
    )


def asked(ynab_api: YnabClientStub) -> list[dt.date]:
    """The months YNAB was asked for since the last time this was read."""
    mock = ynab_api.api("months").get_plan_month
    months = [call.args[1] for call in mock.call_args_list]
    mock.reset_mock()
    return months


@freeze_time("2025-05-15 10:00:00")
def test_a_sync_keeps_what_categories_held_in_the_months_that_ended(
    store: Store, client: Client, ynab_api: YnabClientStub
):
    serve(ynab_api, [MARCH, APRIL, MAY, JUNE], {MARCH: 1_000, APRIL: 1_500, MAY: 9_999})

    store.sync(client, BUDGET_ID)

    # The month running and the one after are not past: their figures still move
    assert asked(ynab_api) == [APRIL, MARCH]
    assert store.category_balances(BUDGET_ID, str(GOAL)) == {MARCH: 1_000, APRIL: 1_500}


def test_a_later_sync_only_asks_for_what_it_does_not_hold(
    store: Store, client: Client, ynab_api: YnabClientStub
):
    serve(ynab_api, [MARCH, APRIL, MAY, JUNE], {MARCH: 1_000, APRIL: 1_500, MAY: 2_000})
    with freeze_time("2025-05-15 10:00:00") as clock:
        store.sync(client, BUDGET_ID)
        asked(ynab_api)

        clock.move_to("2025-05-15 18:00:00")
        store.sync(client, BUDGET_ID)
        assert asked(ynab_api) == []

        # Money is still assigned in a month while it is being closed: once a day, the last
        # one is read again
        serve(ynab_api, [MARCH, APRIL, MAY, JUNE], {MARCH: 7, APRIL: 1_800, MAY: 2_000})
        clock.move_to("2025-05-16 09:00:00")
        store.sync(client, BUDGET_ID)
        assert asked(ynab_api) == [APRIL]
        assert store.category_balances(BUDGET_ID, str(GOAL)) == {MARCH: 1_000, APRIL: 1_800}

        clock.move_to("2025-06-02 09:00:00")
        store.sync(client, BUDGET_ID)
        assert asked(ynab_api) == [MAY]
        assert store.category_balances(BUDGET_ID, str(GOAL))[MAY] == 2_000


@freeze_time("2025-05-15 10:00:00")
def test_fetching_everything_again_reads_every_past_month_again(
    store: Store, client: Client, ynab_api: YnabClientStub
):
    serve(ynab_api, [MARCH, APRIL, MAY], {MARCH: 1_000, APRIL: 1_500})
    store.sync(client, BUDGET_ID)
    asked(ynab_api)
    store.clear(BUDGET_ID)
    assert store.category_balances(BUDGET_ID, str(GOAL)) == {}

    serve(ynab_api, [MARCH, APRIL, MAY], {MARCH: 1_100, APRIL: 1_500})
    store.sync(client, BUDGET_ID)

    assert asked(ynab_api) == [APRIL, MARCH]
    assert store.category_balances(BUDGET_ID, str(GOAL)) == {MARCH: 1_100, APRIL: 1_500}


@freeze_time("2025-05-15 10:00:00")
def test_a_long_budget_keeps_its_last_past_months_only(
    store: Store, client: Client, ynab_api: YnabClientStub
):
    months = [dt.date(2020 + index // 12, index % 12 + 1, 1) for index in range(65)]
    serve(ynab_api, months, {})

    store.sync(client, BUDGET_ID)

    fetched = asked(ynab_api)
    assert len(fetched) == PAST_MONTHS
    assert (fetched[0], fetched[-1]) == (APRIL, dt.date(2022, 5, 1))
