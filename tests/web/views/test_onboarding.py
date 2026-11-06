import threading
import uuid
from collections.abc import Callable

import pytest
from nicegui import ui
from nicegui.testing.user import User
from pytest_mock import MockerFixture
from ynab import (
    AccountsResponse,
    AccountsResponseData,
    ApiException,
    TransactionsResponse,
    TransactionsResponseData,
)

from tests.factories import (
    AccountFactory,
    PlanDetailFactory,
    PlanSummaryFactory,
    TransactionDetailFactory,
)
from tests.helpers.config import ConfigFiles
from tests.helpers.keychain import MemoryKeyring
from tests.helpers.ynab_api import YnabClientStub
from ynab_unlinked import keychain
from ynab_unlinked.config import LatestConfig
from ynab_unlinked.web.state import state
from ynab_unlinked.web.wording import SAVE_FAILED, copy_line

pytestmark = pytest.mark.version("missing")

CHECKING = AccountFactory(id=uuid.UUID(int=10), name="💶 Sabadell Checking", type="checking")
CARD = AccountFactory(id=uuid.UUID(int=20), name="💳 Oro", type="creditCard")
BROKER = AccountFactory(id=uuid.UUID(int=30), name="📈 INDEXA", type="otherAsset", on_budget=False)
OLD = AccountFactory(id=uuid.UUID(int=40), name="Old card", type="creditCard", closed=True)
SPARE = AccountFactory(id=uuid.UUID(int=50), name="💸 Chatarra", type="cash")
GONE = AccountFactory(id=uuid.UUID(int=60), name="Gone", type="cash", deleted=True)
ACCOUNTS = [CHECKING, CARD, BROKER, OLD, SPARE, GONE]
OTHER_BUDGET = PlanSummaryFactory(id=uuid.UUID(int=2), name="Holidays", accounts=[SPARE])


@pytest.fixture
def ynab(ynab_api: YnabClientStub) -> YnabClientStub:
    ynab_api.api("budget").get_plans.return_value.data.plans = [
        PlanSummaryFactory(accounts=ACCOUNTS)
    ]
    ynab_api.api("budget").get_plan_by_id.return_value.data.plan = PlanDetailFactory()
    ynab_api.api("accounts").get_accounts.return_value = AccountsResponse(
        data=AccountsResponseData(accounts=ACCOUNTS, server_knowledge=1)
    )
    ynab_api.api("transactions").get_transactions.return_value = TransactionsResponse(
        data=TransactionsResponseData(
            transactions=[TransactionDetailFactory(account_id=CHECKING.id)], server_knowledge=7
        )
    )
    return ynab_api


def held_until(event: threading.Event, answer: object) -> Callable[..., object]:
    """A YNAB call that answers only once the test sets `event`."""

    def call(*args: object, **kwargs: object) -> object:
        event.wait(10)
        return answer

    return call


def element[T: ui.element](user: User, marker: str, kind: type[T]) -> T:
    found = user.find(marker=marker).elements.pop()
    assert isinstance(found, kind)
    return found


async def _walk_to_budget(user: User) -> None:
    await user.open("/")
    user.find(marker="token-input").type("my-new-token")
    user.find(marker="wizard-next").click()
    await user.should_see("Pick a budget", retries=20)


async def _walk_to_banks(user: User) -> None:
    await _walk_to_budget(user)
    await user.should_see("EUR · 4 accounts")
    user.find(marker="wizard-next").click()
    await user.should_see(marker="loader-sabadell", retries=20)


async def test_onboarding_writes_the_config_copies_the_budget_and_opens_yul(
    user: User, ynab: YnabClientStub
):
    await _walk_to_banks(user)
    await user.should_see("You can change this later in Settings › Banks.")

    sabadell = element(user, "loader-sabadell", ui.select)
    # Every open account of the budget, by name, the one named after the bank preselected
    open_accounts = sorted((CHECKING, CARD, BROKER, SPARE), key=lambda account: account.name)
    assert list(sabadell.options) == [str(account.id) for account in open_accounts]
    assert sabadell.value == str(CHECKING.id)
    sabadell.set_value(str(CARD.id))
    user.find(marker="wizard-next").click()

    await user.should_see("You are set", retries=20)
    await user.should_see("Drop your first statements whenever you like.")
    config = LatestConfig.load()
    assert config.api_key == "my-new-token"
    assert config.budget.name == "My Budget"
    assert config.budget.currency_format.iso_code == "EUR"
    assert config.loaders["sabadell"].account_id == str(CARD.id)
    assert config.accounts == []
    ynab.api("budget").get_plans.assert_called_with(include_accounts=True)
    assert state().last_sync is not None
    assert state().store.accounts(config.budget.id)

    user.find(marker="open-yul").click()
    await user.should_see(marker="nav-home")


async def test_picking_a_budget_marks_its_tile_without_drawing_the_grid_again(
    user: User, ynab: YnabClientStub
):
    ynab.api("budget").get_plans.return_value.data.plans = [
        PlanSummaryFactory(accounts=ACCOUNTS),
        OTHER_BUDGET,
    ]
    await _walk_to_budget(user)
    mine = element(user, f"budget-{uuid.UUID(int=1)}", ui.element)
    other = element(user, f"budget-{OTHER_BUDGET.id}", ui.element)
    assert not element(user, "wizard-next", ui.button).enabled

    user.find(marker=f"budget-{OTHER_BUDGET.id}").click()
    assert "on" in other.classes
    assert element(user, "wizard-next", ui.button).enabled

    user.find(marker=f"budget-{uuid.UUID(int=1)}").click()
    assert "on" in mine.classes
    assert "on" not in other.classes
    # The same tiles, so they did not enter again
    assert element(user, f"budget-{uuid.UUID(int=1)}", ui.element) is mine
    assert element(user, f"budget-{OTHER_BUDGET.id}", ui.element) is other


async def test_the_banks_step_reads_the_accounts_before_showing_the_banks(
    user: User, ynab: YnabClientStub
):
    answer = threading.Event()
    accounts = ynab.api("accounts").get_accounts
    accounts.side_effect = held_until(answer, accounts.return_value)
    await _walk_to_budget(user)
    user.find(marker="wizard-next").click()

    await user.should_see(marker="loading-accounts", retries=20)
    await user.should_see("Reading your accounts…")
    await user.should_not_see(marker="loader-sabadell")
    assert not element(user, "wizard-next", ui.button).enabled

    answer.set()
    await user.should_see(marker="loader-sabadell", retries=20)
    await user.should_not_see(marker="loading-accounts")
    assert element(user, "wizard-next", ui.button).enabled


async def test_the_banks_step_explains_a_failure_and_tries_again(user: User, ynab: YnabClientStub):
    accounts = ynab.api("accounts").get_accounts
    accounts.side_effect = ApiException(status=500, reason="Server Error")
    await _walk_to_budget(user)
    user.find(marker="wizard-next").click()

    await user.should_see(marker="accounts-error", retries=20)
    await user.should_see("YNAB answered 500: Server Error")
    assert not element(user, "wizard-next", ui.button).enabled

    accounts.side_effect = None
    user.find(marker="accounts-retry").click()
    await user.should_see(marker="loader-sabadell", retries=20)
    assert element(user, "wizard-next", ui.button).enabled


async def test_back_works_after_the_accounts_failed(user: User, ynab: YnabClientStub):
    ynab.api("accounts").get_accounts.side_effect = ApiException(status=500, reason="Down")
    await _walk_to_budget(user)
    user.find(marker="wizard-next").click()
    await user.should_see(marker="accounts-error", retries=20)

    user.find(marker="wizard-back").click()
    await user.should_see("Pick a budget")


async def test_done_follows_the_first_copy_until_it_is_set(user: User, ynab: YnabClientStub):
    await _walk_to_banks(user)
    answer = threading.Event()
    transactions = ynab.api("transactions").get_transactions
    transactions.side_effect = held_until(answer, transactions.return_value)
    user.find(marker="wizard-next").click()

    await user.should_see("Copying your budget from YNAB", retries=20)
    await user.should_see("The first time can take a minute.")
    await user.should_see("Fetching all transactions from YNAB", retries=20)
    await user.should_not_see(marker="open-yul")
    assert LatestConfig.load().accounts == []

    answer.set()
    await user.should_see("You are set", retries=20)
    await user.should_see(marker="open-yul")


async def test_a_failed_first_copy_offers_to_try_again_or_open_yul(
    user: User, ynab: YnabClientStub
):
    await _walk_to_banks(user)
    transactions = ynab.api("transactions").get_transactions
    transactions.side_effect = ApiException(status=500, reason="Server Error")
    user.find(marker="wizard-next").click()

    await user.should_see(marker="copy-error", retries=20)
    await user.should_see("YNAB answered 500: Server Error")
    await user.should_see(marker="open-yul")

    transactions.side_effect = None
    user.find(marker="copy-retry").click()
    await user.should_see("You are set", retries=20)


def test_the_copy_line_speaks_the_users_words():
    assert copy_line("8630 transactions received") == "8,630 transactions received"
    assert copy_line("Saving to the local store") == "Saving the copy on this computer"


async def test_a_rejected_token_is_explained_inline(user: User, ynab: YnabClientStub):
    ynab.api("budget").get_plans.side_effect = ApiException(status=401, reason="Unauthorized")
    await user.open("/onboarding")

    user.find(marker="token-input").type("wrong")
    user.find(marker="check-token").click()

    await user.should_see("YNAB rejected this token", retries=20)
    await user.should_not_see("Pick a budget")


@pytest.mark.version("V4")
async def test_a_token_gone_from_the_keychain_is_asked_for_and_the_rest_is_kept(
    ynab: YnabClientStub, memory_keychain: MemoryKeyring, config_v4: LatestConfig, user: User
):
    config_v4.save()  # the token moves to the keychain
    memory_keychain.passwords.clear()
    state().reload()
    await user.open("/")
    await user.should_see(marker="token-lost")
    await user.should_see("Your budget, banks and accounts are kept.")

    user.find(marker="token-input").type("my-new-token")
    user.find(marker="check-token").click()

    await user.should_see(marker="nav-home", retries=20)
    config = LatestConfig.load()
    assert config.api_key == "my-new-token"
    assert config.loaders == config_v4.loaders
    assert memory_keychain.passwords[(keychain.service_name(), keychain.ACCOUNT)] == "my-new-token"


@pytest.mark.version("V4")
@pytest.mark.parametrize("file_gone", [False, True], ids=["saved", "file-gone"])
async def test_recovering_the_token_keeps_the_config_without_its_file_and_toasts_a_failed_save(
    ynab: YnabClientStub,
    memory_keychain: MemoryKeyring,
    config_v4: LatestConfig,
    config_files: ConfigFiles,
    user: User,
    mocker: MockerFixture,
    file_gone: bool,
):
    config_v4.save()  # the token moves to the keychain
    memory_keychain.passwords.clear()
    state().reload()
    await user.open("/")
    await user.should_see(marker="token-lost")
    if file_gone:
        # The kept config is the fallback of this one save, so the budget and banks survive
        config_files.path("V4").unlink()
    else:
        mocker.patch.object(LatestConfig, "save", side_effect=OSError("disk full"))

    user.find(marker="token-input").type("my-new-token")
    user.find(marker="check-token").click()

    if file_gone:
        await user.should_see(marker="nav-home", retries=20)
        assert LatestConfig.load().loaders == config_v4.loaders
    else:
        await user.should_see(SAVE_FAILED, retries=20)
        await user.should_see(marker="token-lost")
