import uuid
from pathlib import Path

import pytest
from nicegui.testing.user import User
from ynab import (
    CategoriesResponse,
    CategoriesResponseData,
    TransactionsResponse,
    TransactionsResponseData,
)

from tests.factories import CategoryFactory, CategoryGroupFactory
from tests.helpers.web import eventually
from tests.helpers.ynab_api import YnabClientStub
from ynab_unlinked.config import LatestConfig, get_config
from ynab_unlinked.store import Store
from ynab_unlinked.ynab_api import Client

pytestmark = pytest.mark.version("V4")

BUDGET_ID = "00000000-0000-0000-0000-000000000001"
EATING = str(uuid.UUID(int=1001))
BROKER = str(uuid.UUID(int=1002))
DOWN = str(uuid.UUID(int=1003))
TRIP = str(uuid.UUID(int=1004))


@pytest.fixture
def categories(config_v4: LatestConfig, ynab_api: YnabClientStub, store_file: Path) -> Store:
    ynab_api.api("categories").get_categories.return_value = CategoriesResponse(
        data=CategoriesResponseData(
            category_groups=[
                CategoryGroupFactory(
                    id=uuid.UUID(int=901),
                    name="Everyday",
                    categories=[CategoryFactory(id=uuid.UUID(EATING), name="🍕 Eating out")],
                ),
                CategoryGroupFactory(
                    id=uuid.UUID(int=902),
                    name="Goals",
                    categories=[
                        CategoryFactory(id=uuid.UUID(BROKER), name="📈 Broker"),
                        CategoryFactory(
                            id=uuid.UUID(DOWN),
                            name="🏠 Down Payment",
                            goal_type="TB",
                            goal_target=70_000_000,
                        ),
                        CategoryFactory(
                            id=uuid.UUID(TRIP),
                            name="🏝 Vacation",
                            goal_type="TBD",
                            goal_target=3_000_000,
                        ),
                    ],
                ),
            ],
            server_knowledge=1,
        )
    )
    ynab_api.api("transactions").get_transactions.return_value = TransactionsResponse(
        data=TransactionsResponseData(transactions=[], server_knowledge=1)
    )
    store = Store(store_file)
    store.sync(Client("api-key"), BUDGET_ID)
    return store


async def open_tab(user: User, slug: str, marker: str) -> None:
    await user.open(f"/settings?tab={slug}")
    await user.should_see(marker=marker, retries=20)


async def test_before_a_sync_the_tab_says_categories_come_with_it(
    config_v4: LatestConfig, user: User
):
    await open_tab(user, "categories", "category-rules")

    await user.should_see(marker="no-categories")


async def test_a_category_picked_is_not_spending_until_removed(categories: Store, user: User):
    await open_tab(user, "categories", "add-not-spending")

    user.find(marker="add-not-spending").click()
    user.find(marker=f"add-not-spending-{BROKER}").click()

    await eventually(lambda: get_config().finances.not_spending == [BROKER])
    await user.should_see(marker=f"not-spending-{BROKER}", retries=20)

    user.find(marker=f"spending-again-{BROKER}").click()

    await eventually(lambda: get_config().finances.not_spending == [])


async def test_typing_in_the_picker_keeps_only_the_matching_categories(
    categories: Store, user: User
):
    await open_tab(user, "categories", "add-not-spending")
    user.find(marker="add-not-spending").click()

    user.find(marker="add-not-spending-search").type("eat")

    await user.should_see(marker=f"add-not-spending-{EATING}")
    await user.should_not_see(marker=f"add-not-spending-{BROKER}", retries=20)


async def test_the_goal_is_the_largest_target_until_another_is_picked(
    categories: Store, user: User
):
    await open_tab(user, "networth", "goal")
    await user.should_see("🏠 Down Payment · 70,000.00€")

    user.find(marker="pick-goal").click()
    user.find(marker=f"pick-goal-{TRIP}").click()

    await eventually(lambda: get_config().finances.goal_category_id == TRIP)
    await user.should_see("🏝 Vacation · 3,000.00€", retries=20)

    user.find(marker="goal-default").click()

    await eventually(lambda: get_config().finances.goal_category_id is None)


async def test_the_goal_picker_only_lists_balance_targets(categories: Store, user: User):
    await open_tab(user, "networth", "goal")
    user.find(marker="pick-goal").click()

    await user.should_see(marker=f"pick-goal-{DOWN}")
    await user.should_not_see(marker=f"pick-goal-{EATING}")


async def test_without_a_balance_target_there_is_no_goal(config_v4: LatestConfig, user: User):
    await open_tab(user, "networth", "save-networth")

    await user.should_see(marker="no-goal")
