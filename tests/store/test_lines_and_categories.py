import datetime as dt
import sqlite3
import uuid
from contextlib import closing
from pathlib import Path

import pytest
from ynab import (
    CategoriesResponse,
    CategoriesResponseData,
    CategoryGroupWithCategories,
    TransactionsResponse,
    TransactionsResponseData,
)

from tests.factories import (
    CategoryFactory,
    CategoryGroupFactory,
    SubTransactionFactory,
    TransactionDetailFactory,
)
from tests.helpers.ynab_api import YnabClientStub
from ynab_unlinked.store import Line, Store, StoredCategory
from ynab_unlinked.store.migrations import MIGRATIONS, apply
from ynab_unlinked.ynab_api import Client

BUDGET_ID = "budget-1"
CHECKING = uuid.UUID(int=1)
CASH_CARD = uuid.UUID(int=3)
RENT = uuid.UUID(int=11)
INCOME = uuid.UUID(int=12)


@pytest.fixture
def store(tmp_path: Path) -> Store:
    return Store(tmp_path / "store.sqlite")


@pytest.fixture
def client(ynab_api: YnabClientStub) -> Client:
    return Client(api_key="an-api-key")


def serve(ynab_api: YnabClientStub, *fetches, groups: list[CategoryGroupWithCategories] = ()):
    ynab_api.api("transactions").get_transactions.side_effect = [
        TransactionsResponse(
            data=TransactionsResponseData(transactions=list(rows), server_knowledge=knowledge)
        )
        for rows, knowledge in fetches
    ]
    ynab_api.api("categories").get_categories.return_value = CategoriesResponse(
        data=CategoriesResponseData(category_groups=list(groups), server_knowledge=1)
    )


def paycheck(*subtransactions) -> object:
    return TransactionDetailFactory(
        id="pay",
        account_id=CHECKING,
        var_date=dt.date(2025, 5, 1),
        amount=sum(sub.amount for sub in subtransactions),
        payee_name="Employer",
        category_name="Split",
        subtransactions=list(subtransactions),
    )


def test_a_split_transaction_reads_as_its_lines(store: Store, client: Client, ynab_api):
    serve(
        ynab_api,
        (
            [
                paycheck(
                    SubTransactionFactory(
                        id="s1", amount=3_000_000, category_id=INCOME, category_name="Inflow"
                    ),
                    SubTransactionFactory(
                        id="s2",
                        amount=-200_000,
                        payee_name="Transfer : Meal card",
                        transfer_account_id=CASH_CARD,
                    ),
                ),
                TransactionDetailFactory(
                    id="rent",
                    account_id=CHECKING,
                    var_date=dt.date(2025, 5, 2),
                    amount=-900_000,
                    category_id=RENT,
                    category_name="Rent",
                ),
            ],
            10,
        ),
    )

    store.sync(client, BUDGET_ID)

    assert store.lines(BUDGET_ID) == [
        Line(
            "pay",
            str(CHECKING),
            dt.date(2025, 5, 1),
            3_000_000,
            "Employer",
            str(INCOME),
            "Inflow",
            None,
        ),
        Line(
            "pay",
            str(CHECKING),
            dt.date(2025, 5, 1),
            -200_000,
            "Transfer : Meal card",
            None,
            None,
            str(CASH_CARD),
        ),
        Line(
            "rent",
            str(CHECKING),
            dt.date(2025, 5, 2),
            -900_000,
            "Mercadona",
            str(RENT),
            "Rent",
            None,
        ),
    ]
    assert sum(line.amount for line in store.lines(BUDGET_ID)) == sum(
        t.amount for t in store.transactions(BUDGET_ID)
    )


def test_a_split_changed_in_ynab_keeps_only_its_new_lines(store: Store, client: Client, ynab_api):
    before = paycheck(
        SubTransactionFactory(id="s1", amount=-100), SubTransactionFactory(id="s2", amount=-200)
    )
    after = paycheck(SubTransactionFactory(id="s3", amount=-300))
    serve(ynab_api, ([before], 10), ([after], 11))

    store.sync(client, BUDGET_ID)
    store.sync(client, BUDGET_ID)

    assert [line.amount for line in store.lines(BUDGET_ID)] == [-300]


def test_lines_of_a_deleted_split_are_gone(store: Store, client: Client, ynab_api):
    split = paycheck(SubTransactionFactory(id="s1", amount=-100))
    deleted = paycheck(SubTransactionFactory(id="s1", amount=-100))
    deleted.deleted = True
    serve(ynab_api, ([split], 10), ([deleted], 11))

    store.sync(client, BUDGET_ID)
    store.sync(client, BUDGET_ID)

    assert store.lines(BUDGET_ID) == []


def test_lines_are_filtered_by_date(store: Store, client: Client, ynab_api):
    serve(
        ynab_api,
        (
            [
                TransactionDetailFactory(id=f"t{day}", var_date=dt.date(2025, 5, day))
                for day in (1, 2, 3)
            ],
            10,
        ),
    )
    store.sync(client, BUDGET_ID)

    lines = store.lines(BUDGET_ID, since=dt.date(2025, 5, 2), until=dt.date(2025, 5, 2))

    assert [line.transaction_id for line in lines] == ["t2"]


def test_categories_are_kept_in_ynab_order_with_their_group_and_goal(
    store: Store, client: Client, ynab_api
):
    serve(
        ynab_api,
        ([], 10),
        groups=[
            CategoryGroupFactory(
                id=uuid.UUID(int=901),
                name="Internal Master Category",
                internal=True,
                categories=[CategoryFactory(id=INCOME, name="Inflow: Ready to Assign")],
            ),
            CategoryGroupFactory(
                id=uuid.UUID(int=902),
                name="Savings",
                hidden=True,
                categories=[
                    CategoryFactory(
                        id=RENT,
                        name="Down Payment",
                        balance=44_000_000,
                        goal_type="TB",
                        goal_target=70_000_000,
                        goal_target_date=dt.date(2028, 1, 1),
                        note="for the flat",
                    ),
                    CategoryFactory(name="Old one", deleted=True),
                ],
            ),
            CategoryGroupFactory(
                id=uuid.UUID(int=903), name="Gone", deleted=True, categories=[CategoryFactory()]
            ),
        ],
    )

    result = store.sync(client, BUDGET_ID)

    assert result.categories == 3
    assert store.categories(BUDGET_ID) == [
        StoredCategory(
            id=str(INCOME),
            name="Inflow: Ready to Assign",
            group_id=str(uuid.UUID(int=901)),
            group_name="Internal Master Category",
            hidden=False,
            internal=True,
            balance=0,
        ),
        StoredCategory(
            id=str(RENT),
            name="Down Payment",
            group_id=str(uuid.UUID(int=902)),
            group_name="Savings",
            hidden=True,
            internal=False,
            balance=44_000_000,
            goal_type="TB",
            goal_target=70_000_000,
            goal_target_date=dt.date(2028, 1, 1),
            note="for the flat",
        ),
    ]


def test_categories_are_replaced_on_every_sync(store: Store, client: Client, ynab_api):
    serve(
        ynab_api,
        ([], 10),
        ([], 11),
        groups=[CategoryGroupFactory(categories=[CategoryFactory(name="Rent")])],
    )
    store.sync(client, BUDGET_ID)
    ynab_api.api("categories").get_categories.return_value = CategoriesResponse(
        data=CategoriesResponseData(
            category_groups=[CategoryGroupFactory(categories=[CategoryFactory(name="Housing")])],
            server_knowledge=2,
        )
    )

    store.sync(client, BUDGET_ID)

    assert [category.name for category in store.categories(BUDGET_ID)] == ["Housing"]


def test_a_store_of_schema_5_syncs_everything_again_to_fill_the_new_data(tmp_path: Path):
    path = tmp_path / "store.sqlite"
    with closing(sqlite3.connect(path)) as old:
        apply(old, MIGRATIONS[:5])
        old.execute(
            "INSERT INTO sync_state (budget_id, server_knowledge, synced_at) "
            "VALUES ('budget', 42, '2025-05-01T10:00:00.000000+00:00')"
        )
        old.execute(
            "INSERT INTO transactions (budget_id, id, account_id, date, amount, cleared, "
            "approved, deleted) VALUES ('budget', 't1', 'a', '2025-05-01', -1, 'cleared', 1, 0)"
        )
        old.commit()

    store = Store(path)

    assert store.last_sync("budget") is None
    assert [t.id for t in store.transactions("budget")] == ["t1"]
