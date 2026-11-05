import datetime as dt
import uuid
from pathlib import Path

import pytest
from nicegui import ui
from nicegui.testing.user import User

from tests.factories import AccountFactory, PlanSummaryFactory, TransactionDetailFactory
from tests.helpers.config import ConfigFiles
from tests.helpers.ynab_api import YnabClientStub
from ynab_unlinked.buckets import Bucket
from ynab_unlinked.config import ClearedStatus, DebtMapping, LatestConfig, TrackedAccount
from ynab_unlinked.keychain import mask_token
from ynab_unlinked.store import Store
from ynab_unlinked.web.state import state
from ynab_unlinked.web.views.settings import tab_from_slug

pytestmark = pytest.mark.version("V4")


CHECKING_ID = str(uuid.UUID(int=10))
CARD_ID = str(uuid.UUID(int=20))
SAVINGS_ID = str(uuid.UUID(int=40))


@pytest.fixture
def tracked(config_v4: LatestConfig, ynab_api: YnabClientStub) -> LatestConfig:
    """Three open accounts with one debt. Request it before `user`, which reads the config."""
    ynab_api.api("accounts").get_accounts.return_value.data.accounts = [
        AccountFactory(id=uuid.UUID(int=10), name="💶 Checking", type="checking"),
        AccountFactory(id=uuid.UUID(int=40), name="💰 Savings", type="savings"),
        AccountFactory(id=uuid.UUID(int=20), name="💳 Oro", type="creditCard"),
    ]
    config_v4.accounts = [
        TrackedAccount(id=CHECKING_ID, name="💶 Checking", type="checking", bucket=Bucket.CASH),
    ]
    config_v4.save()
    return config_v4


async def _open_tab(user: User, tab: str) -> None:
    await user.open("/settings")
    user.find(marker=f"tab-{tab}").click()


async def test_net_worth_saves_the_adjustment_memo_and_a_debt_mapping(
    tracked: LatestConfig, user: User
):
    await _open_tab(user, "net-worth")
    await user.should_see(marker=f"mapping-{CARD_ID}", retries=20)
    await user.should_see("not netted")

    add = user.find(marker=f"map-{CARD_ID}").elements.pop()
    assert isinstance(add, ui.select)
    assert set(add.options) == {CHECKING_ID, SAVINGS_ID}
    add.set_value(CHECKING_ID)
    await user.should_not_see("not netted")
    user.find(marker="memo").clear().type("Adjusted by hand")
    cleared = user.find(marker="cleared").elements.pop()
    assert isinstance(cleared, ui.select)
    cleared.set_value("reconciled")
    user.find(marker="save-networth").click()

    await user.should_see("Net worth settings saved")
    saved = LatestConfig.load()
    assert saved.adjustments.memo == "Adjusted by hand"
    assert saved.adjustments.cleared is ClearedStatus.RECONCILED
    assert [(m.debt_account_id, m.mapped_to) for m in saved.debt_mappings] == [
        (CARD_ID, [CHECKING_ID])
    ]


async def test_net_worth_keeps_the_mappings_of_debts_it_does_not_list(
    tracked: LatestConfig, user: User
):
    tracked.accounts.append(
        TrackedAccount(
            id=CARD_ID, name="💳 Oro", type="creditCard", bucket=Bucket.DEBT, counted=False
        )
    )
    tracked.debt_mappings = [DebtMapping(debt_account_id=CARD_ID, mapped_to=[CHECKING_ID])]
    tracked.save()
    state().reload()
    await _open_tab(user, "net-worth")
    await user.should_see("Count a credit card or a loan in Accounts to map it here.", retries=20)

    user.find(marker="save-networth").click()

    await user.should_see("Net worth settings saved")
    assert LatestConfig.load().debt_mappings == tracked.debt_mappings


async def test_an_empty_adjustment_payee_is_not_saved(tracked: LatestConfig, user: User):
    await _open_tab(user, "net-worth")
    await user.should_see(marker="payee", retries=20)

    user.find(marker="payee").clear()
    user.find(marker="save-networth").click()

    await user.should_see("The adjustment payee cannot be empty")
    assert LatestConfig.load().adjustments.payee == "Balance Adjustment"


@pytest.mark.parametrize(
    ("query", "shown", "hidden"),
    [
        ("?tab=net-worth", "memo", "token-value"),
        ("?tab=nonsense", "token-value", "memo"),
    ],
    ids=["named-tab", "unknown-tab-falls-back-to-connection"],
)
async def test_a_deep_link_opens_the_tab_it_names(
    tracked: LatestConfig, user: User, query: str, shown: str, hidden: str
):
    await user.open(f"/settings{query}")

    await user.should_see(marker=shown, retries=20)
    await user.should_not_see(marker=hidden)


async def test_the_token_is_masked_until_revealed(user: User, config_v4: LatestConfig):
    await user.open("/settings")
    await user.should_see(mask_token("my-api-key"))
    await user.should_not_see("my-api-key")

    user.find(marker="reveal-token").click()

    await user.should_see("my-api-key")


@pytest.mark.parametrize(
    ("budget_id", "saved_token", "message"),
    [
        (uuid.UUID(int=1), "a-new-token", "Token updated"),
        (uuid.UUID(int=99), "my-api-key", "This token cannot see the budget"),
    ],
    ids=["same-budget", "other-account"],
)
async def test_a_new_token_is_saved_only_if_it_sees_the_budget(
    user: User,
    config_v4: LatestConfig,
    ynab_api: YnabClientStub,
    budget_id: uuid.UUID,
    saved_token: str,
    message: str,
):
    ynab_api.api("budget").get_plans.return_value.data.plans = [PlanSummaryFactory(id=budget_id)]
    await user.open("/settings")

    user.find(marker="change-token").click()
    user.find(marker="new-token").type("a-new-token")
    user.find(marker="save-token").click()

    await user.should_see(message, retries=20)
    assert LatestConfig.load().api_key == saved_token


async def test_the_data_tab_says_where_the_token_is_without_console_markup(
    user: User, config_v4: LatestConfig
):
    await _open_tab(user, "data-privacy")
    await user.should_see(marker="token-location", retries=20)

    [label] = user.find(marker="token-location").elements
    assert isinstance(label, ui.label)
    assert label.text.startswith("In plaintext at “")
    assert label.text.endswith("(no keychain found on this computer).")
    assert "[cyan]" not in label.text


async def test_resync_rebuilds_the_budget_copy_and_keeps_the_activity(
    user: User, config_v4: LatestConfig, ynab_api: YnabClientStub, store_file: Path
):
    response = ynab_api.api("transactions").get_transactions.return_value
    response.data.transactions = [TransactionDetailFactory(id="t1")]
    response.data.server_knowledge = 7
    ynab_api.api("accounts").get_accounts.return_value.data.accounts = []
    store = Store(store_file)
    store.log(config_v4.budget.id, "import", "Imported 3 transactions")
    await _open_tab(user, "data-privacy")
    await user.should_see(marker="resync", retries=20)

    user.find(marker="resync").click()

    await user.should_see("1 transaction loaded from YNAB", retries=20)
    assert [t.id for t in store.transactions(config_v4.budget.id)] == ["t1"]
    assert "Imported 3 transactions" in [a.message for a in store.activity(config_v4.budget.id)]


async def test_reset_all_data_deletes_everything_and_starts_onboarding(
    user: User, config_v4: LatestConfig, config_files: ConfigFiles, store_file: Path
):
    Store(store_file)
    await _open_tab(user, "data-privacy")
    await user.should_see(str(store_file), retries=20)

    user.find(marker="reset-data").click()
    await user.should_see("Reset all data?", retries=20)
    user.find(marker="confirm-action").click()

    await user.should_see("Connect to YNAB", retries=20)
    assert not config_files.v2.exists()
    assert not store_file.exists()


@pytest.fixture
def budget_accounts(ynab_api: YnabClientStub) -> YnabClientStub:
    ynab_api.api("accounts").get_accounts.return_value.data.accounts = [
        AccountFactory(id=uuid.UUID(int=10), name="💶 Checking", type="checking"),
        AccountFactory(id=uuid.UUID(int=20), name="💳 Oro", type="creditCard"),
        AccountFactory(id=uuid.UUID(int=30), name="Closed", type="checking", closed=True),
    ]
    return ynab_api


async def test_bank_settings_save_the_account_and_only_non_default_options(
    user: User, config_v4: LatestConfig, budget_accounts: YnabClientStub
):
    await _open_tab(user, "banks")
    await user.should_see(marker="bank-settings-bbva", retries=20)
    await user.should_see("Pick the YNAB account its statements go to.", marker="bank-summary-bbva")

    user.find(marker="bank-settings-bbva").click()
    await user.should_see(marker="loader-bbva")
    bbva = user.find(marker="loader-bbva").elements.pop()
    assert isinstance(bbva, ui.select)
    assert "Closed" not in bbva.options.values()
    bbva.set_value(CARD_ID)
    user.find(marker="save-bank-bbva").click()
    await user.should_see("BBVA Credit Card saved")

    user.find(marker="bank-settings-cobee").click()
    await user.should_see(marker="option-cobee-language")
    language = user.find(marker="option-cobee-language").elements.pop()
    assert isinstance(language, ui.select)
    language.set_value("pt")
    user.find(marker="save-bank-cobee").click()
    await user.should_see("Cobee saved")
    await user.should_see("language of the saved page: pt", marker="bank-summary-cobee")

    loaders = LatestConfig.load().loaders
    assert loaders["BBVA Credit Card"].account_id == CARD_ID
    assert loaders["BBVA Credit Card"].enabled
    assert loaders["cobee"].options == {"language": "pt"}
    assert loaders["sabadell"].options == {}
    # Loaders yul does not ship (the test entity) are left alone
    assert loaders["test"].account_id == "TestAccountID"


async def test_a_bank_is_turned_off_and_on_from_its_card(
    user: User, config_v4: LatestConfig, budget_accounts: YnabClientStub
):
    before = config_v4.loaders["sabadell"].account_id
    await _open_tab(user, "banks")
    await user.should_see(marker="bank-toggle-sabadell", retries=20)
    toggle = user.find(marker="bank-toggle-sabadell").elements.pop()
    assert isinstance(toggle, ui.switch)
    assert toggle.value is True

    toggle.set_value(False)

    await user.should_see("Sabadell turned off")
    saved = LatestConfig.load().loaders["sabadell"]
    assert saved.enabled is False
    assert saved.account_id == before

    await user.should_see(marker="bank-toggle-sabadell")
    toggle = user.find(marker="bank-toggle-sabadell").elements.pop()
    assert isinstance(toggle, ui.switch)
    toggle.set_value(True)

    await user.should_see("Sabadell turned on")
    assert LatestConfig.load().loaders["sabadell"].enabled is True


async def test_a_save_from_the_app_keeps_what_the_cli_saved_meanwhile(
    user: User, config_v4: LatestConfig, budget_accounts: YnabClientStub
):
    await _open_tab(user, "banks")
    await user.should_see(marker="bank-toggle-sabadell", retries=20)
    # `yul reconcile` and `yul load` in a terminal while the page is open
    cli = LatestConfig.load()
    cli.last_reconciliation_date = dt.date(2025, 5, 10)
    cli.set_entity_account("cobee", "account-saved-by-the-cli")
    cli.save()

    toggle = user.find(marker="bank-toggle-sabadell").elements.pop()
    assert isinstance(toggle, ui.switch)
    toggle.set_value(False)

    await user.should_see("Sabadell turned off")
    saved = LatestConfig.load()
    assert saved.loaders["sabadell"].enabled is False
    assert saved.last_reconciliation_date == dt.date(2025, 5, 10)
    assert saved.loaders["cobee"].account_id == "account-saved-by-the-cli"
    assert state().config == saved


async def test_turning_on_a_bank_without_an_account_asks_for_one(
    user: User, config_v4: LatestConfig, budget_accounts: YnabClientStub
):
    await _open_tab(user, "banks")
    await user.should_see(marker="bank-toggle-bbva", retries=20)
    toggle = user.find(marker="bank-toggle-bbva").elements.pop()
    assert isinstance(toggle, ui.switch)

    toggle.set_value(True)

    await user.should_see(marker="save-bank-bbva")
    user.find(marker="save-bank-bbva").click()
    await user.should_see("Pick the account its statements go to.")
    assert "BBVA Credit Card" not in LatestConfig.load().loaders


@pytest.fixture
def mapped(config_v4: LatestConfig) -> LatestConfig:
    """No account settings and the card netted from checking. Request it before `user`."""
    config_v4.debt_mappings = [DebtMapping(debt_account_id=CARD_ID, mapped_to=[CHECKING_ID])]
    config_v4.save()
    return config_v4


def _switch(user: User, account_id: str) -> ui.switch:
    switch = user.find(marker=f"account-{account_id}").elements.pop()
    assert isinstance(switch, ui.switch)
    return switch


def _card(user: User, account_id: str) -> ui.element:
    return user.find(marker=f"account-card-{account_id}").elements.pop()


async def test_every_open_account_has_a_card_and_counts_by_default(
    mapped: LatestConfig, user: User, budget_accounts: YnabClientStub
):
    await _open_tab(user, "accounts")
    await user.should_see(marker=f"account-{CHECKING_ID}", retries=20)

    await user.should_see("Every open account counts in your net worth", marker="accounts-lede")
    await user.should_see(marker=f"account-{CARD_ID}")
    await user.should_see(marker=f"bucket-section-{Bucket.DEBT}")
    await user.should_not_see("Closed")
    for account_id in (CHECKING_ID, CARD_ID):
        assert _switch(user, account_id).value is True
        assert "live" in _card(user, account_id).classes
    assert LatestConfig.load().accounts == []


async def test_accounts_save_every_change_and_drop_entries_back_at_their_defaults(
    mapped: LatestConfig, user: User, budget_accounts: YnabClientStub
):
    await _open_tab(user, "accounts")
    await user.should_see(marker=f"account-{CHECKING_ID}", retries=20)

    user.find(marker=f"bucket-{CHECKING_ID}-savings").click()
    await user.should_see(marker="bucket-section-savings")
    await user.should_see("Accounts saved")
    saved = LatestConfig.load()
    assert [(a.id, a.bucket, a.track_balance, a.counted) for a in saved.accounts] == [
        (CHECKING_ID, Bucket.SAVINGS, False, True)
    ]

    user.find(marker=f"by-hand-{CHECKING_ID}").click()
    await user.should_see("Accounts saved")
    assert LatestConfig.load().accounts[0].track_balance is True

    user.find(marker=f"bucket-{CHECKING_ID}-cash").click()
    await user.should_not_see(marker="bucket-section-savings")
    assert LatestConfig.load().accounts[0].bucket is Bucket.CASH

    user.find(marker=f"by-hand-{CHECKING_ID}").click()
    await user.should_see("Accounts saved")
    # Everything is back at its default, so no entry is needed
    assert LatestConfig.load().accounts == []
    assert LatestConfig.load().debt_mappings == mapped.debt_mappings


async def test_switching_an_account_off_leaves_it_out_of_net_worth(
    mapped: LatestConfig, user: User, budget_accounts: YnabClientStub
):
    await _open_tab(user, "accounts")
    await user.should_see(marker=f"account-{CARD_ID}", retries=20)

    user.find(marker=f"account-{CARD_ID}").click()

    await user.should_see("Left out of net worth")
    saved = LatestConfig.load()
    assert [(a.id, a.bucket, a.counted) for a in saved.accounts] == [(CARD_ID, Bucket.DEBT, False)]
    # The mapping stays, ready for when the card counts again
    assert saved.debt_mappings == mapped.debt_mappings
    assert "off" in _card(user, CARD_ID).classes
    assert _switch(user, CARD_ID).value is False

    user.find(marker=f"account-{CARD_ID}").click()

    await user.should_see("Counted in net worth")
    assert LatestConfig.load().accounts == []
    assert "live" in _card(user, CARD_ID).classes


@pytest.mark.parametrize(
    ("slug", "tab"),
    [
        ("connection", "Connection"),
        ("banks", "Banks"),
        ("Accounts", "Accounts"),
        ("networth", "Net worth"),
        ("net-worth", "Net worth"),
        ("privacy", "Data & privacy"),
        ("DATA", "Data & privacy"),
        ("data-privacy", "Data & privacy"),
        ("nonsense", "Connection"),
        (None, "Connection"),
    ],
)
def test_deep_link_slugs_name_their_tab(slug: str | None, tab: str):
    assert tab_from_slug(slug) == tab
