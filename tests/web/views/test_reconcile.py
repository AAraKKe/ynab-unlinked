import datetime as dt
import uuid
from collections.abc import Callable, Sequence
from pathlib import Path

import pytest
from nicegui import ui
from nicegui.testing.user import User
from pytest_mock import MockerFixture
from urllib3.exceptions import MaxRetryError, ReadTimeoutError
from ynab import (
    Account,
    AccountsResponse,
    AccountsResponseData,
    ApiException,
    TransactionClearedStatus,
    TransactionDetail,
    TransactionsResponse,
    TransactionsResponseData,
)

from tests.factories import AccountFactory, TransactionDetailFactory
from tests.helpers.ynab_api import YnabClientStub
from ynab_unlinked.config import LatestConfig
from ynab_unlinked.store import Store, StoredAccount, StoredTransaction
from ynab_unlinked.web.state import AppState, state
from ynab_unlinked.web.views.reconcile.data import (
    LOCK_TIMED_OUT,
    cleared_note,
    gap_candidates,
    lock_confirmation,
    reconcile_label,
    show_label,
    uncleared_note,
)
from ynab_unlinked.web.wording import SAVE_FAILED

pytestmark = pytest.mark.version("V4")

ORO = uuid.UUID(int=101)
CHECKING = uuid.UUID(int=102)
OLD_CARD = uuid.UUID(int=103)

CLEARED = TransactionClearedStatus.CLEARED
UNCLEARED = TransactionClearedStatus.UNCLEARED
RECONCILED = TransactionClearedStatus.RECONCILED

Seed = Callable[..., None]


def oct_(day: int) -> dt.date:
    return dt.date(2026, 10, day)


def tx(
    id_: str, account: uuid.UUID, day: dt.date, amount: int, cleared: TransactionClearedStatus
) -> TransactionDetail:
    return TransactionDetailFactory(
        id=id_, account_id=account, var_date=day, amount=amount, cleared=cleared, payee_name=id_
    )


ACCOUNTS = [
    AccountFactory(
        id=ORO,
        name="💳 Oro",
        type="creditCard",
        cleared_balance=-150_000,
        uncleared_balance=-24_900,
        balance=-174_900,
    ),
    AccountFactory(
        id=CHECKING,
        name="💶 Checking",
        cleared_balance=3_214_200,
        uncleared_balance=-32_170,
        balance=3_182_030,
    ),
    AccountFactory(id=OLD_CARD, name="💳 Old card", closed=True),
]

TRANSACTIONS = [
    tx("oro-mercadona", ORO, oct_(30), -64_120, CLEARED),
    tx("oro-zara", ORO, oct_(26), -24_900, UNCLEARED),
    tx("oro-glovo", ORO, oct_(22), -18_400, CLEARED),
    tx("oro-done", ORO, oct_(20), -5_000, RECONCILED),
    tx("chk-payroll", CHECKING, oct_(31), 4_120_000, CLEARED),
    tx("chk-gym", CHECKING, oct_(29), -32_170, UNCLEARED),
    tx("old-card", OLD_CARD, oct_(29), -1_000, UNCLEARED),
]


@pytest.fixture
def seed(ynab_api: YnabClientStub, store_file: Path, config_v4: LatestConfig) -> Seed:
    """Fill the store through a sync with the stubbed YNAB, as `yul app` would.

    `fresh=True` also records the sync in the app, as the sync at start does: the view syncs
    again when it opens and finds nothing new, and a failed sync still has a copy to show.
    """
    budget_id = config_v4.budget.id

    def fill(
        accounts: Sequence[Account] = ACCOUNTS,
        transactions: Sequence[TransactionDetail] = TRANSACTIONS,
        *,
        fresh: bool = True,
    ) -> None:
        ynab_api.api("transactions").get_transactions.return_value = TransactionsResponse(
            data=TransactionsResponseData(transactions=list(transactions), server_knowledge=1)
        )
        ynab_api.api("accounts").get_accounts.return_value = AccountsResponse(
            data=AccountsResponseData(accounts=list(accounts), server_knowledge=1)
        )
        if fresh:
            store = Store(store_file)
            store.sync(state().require()[1], budget_id)
            state().last_sync = store.last_sync(budget_id)

    return fill


def updated(ynab_api: YnabClientStub) -> dict[str, TransactionClearedStatus]:
    call = ynab_api.api("transactions").update_transactions.call_args
    assert call is not None, "YNAB was not asked to update anything"
    sent = call.kwargs["data"].transactions
    # The account of the stored row could be stale: sending it would move the transaction back
    assert all(t.account_id is None for t in sent)
    return {t.id: t.cleared for t in sent}


def classes(user: User, marker: str) -> list[str]:
    return user.find(marker=marker).elements.pop().classes


def text(user: User, marker: str) -> str:
    """The text of the element with `marker` and of every label in it."""
    element = user.find(marker=marker).elements.pop()
    labels = [element, *element.descendants()]
    return " ".join(label.text for label in labels if isinstance(label, ui.label))


async def open_reconcile(user: User) -> None:
    await user.open("/reconcile")
    await user.should_see(marker="rec-title", retries=20)


async def test_the_header_counts_what_is_left_in_open_accounts(user: User, seed: Seed):
    seed()
    await open_reconcile(user)

    await user.should_see("2 accounts · 5 transactions not reconciled")
    await user.should_see("Reconcile 3 transactions in 2 accounts")
    await user.should_see("uncleared stay untouched")
    await user.should_see("Reconcile all")
    await user.should_see("💳 Oro")
    await user.should_not_see("💳 Old card")


async def test_the_card_header_is_cleared_plus_uncleared_equals_working_balance(
    user: User, seed: Seed
):
    seed()
    await open_reconcile(user)

    card = text(user, f"account-{ORO}")
    assert "-150.00€" in card and "-24.90€" in card and "-174.90€" in card
    assert text(user, f"cleared-{ORO}") == "cleared balance · 2 to reconcile"
    assert text(user, f"uncleared-{ORO}") == "uncleared · 1"
    assert "working balance" in card
    assert text(user, f"cleared-count-{CHECKING}") == "1"
    assert text(user, f"uncleared-count-{CHECKING}") == "1"

    # What is selected is not what is left to reconcile: the switch leaves the counts alone
    user.find(marker="include-uncleared").click()
    await user.should_see("Reconcile 5 transactions in 2 accounts")
    assert text(user, f"cleared-count-{ORO}") == "2"
    assert text(user, f"uncleared-count-{ORO}") == "1"


async def test_a_collapsed_card_shows_its_rows_before_it_can_be_reconciled(user: User, seed: Seed):
    seed()
    await open_reconcile(user)

    assert text(user, f"toggle-{ORO}") == "Show 3 transactions"
    assert text(user, f"toggle-{CHECKING}") == "Show 2 transactions"
    await user.should_not_see(marker=f"lock-{ORO}")
    await user.should_not_see(marker="row-oro-glovo")

    user.find(marker=f"toggle-{ORO}").click()

    await user.should_see(marker=f"lock-{ORO}")
    await user.should_see(marker="row-oro-glovo")
    assert text(user, f"toggle-{ORO}") == "Hide transactions"
    assert text(user, f"lock-{ORO}") == "Reconcile 2 transactions"
    assert "open" in classes(user, f"bar-{ORO}")
    await user.should_not_see(marker=f"lock-{CHECKING}")

    user.find(marker="row-oro-glovo").click()
    user.find(marker="row-oro-mercadona").click()
    assert text(user, f"lock-{ORO}") == "Nothing to reconcile"
    assert not user.find(marker=f"lock-{ORO}").elements.pop().enabled

    user.find(marker=f"toggle-{ORO}").click()
    await user.should_not_see(marker=f"lock-{ORO}")
    assert text(user, f"toggle-{ORO}") == "Show 3 transactions"


async def test_rows_are_grouped_under_what_their_status_means(user: User, seed: Seed):
    seed()
    await open_reconcile(user)
    user.find(marker=f"toggle-{ORO}").click()

    await user.should_see(marker=f"section-cleared-{ORO}")
    assert text(user, f"note-cleared-{ORO}") == "the bank shows these · 2 to reconcile"
    assert text(user, f"note-uncleared-{ORO}") == "the bank has not taken these yet · skipped"
    await user.should_not_see(marker=f"section-reconciled-{ORO}")
    drawn = list(user.find(marker=f"rows-{ORO}").elements.pop().descendants())
    order = [
        f"section-cleared-{ORO}",
        "row-oro-mercadona",
        "row-oro-glovo",
        f"section-uncleared-{ORO}",
        "row-oro-zara",
    ]
    positions = [drawn.index(user.find(marker=marker).elements.pop()) for marker in order]
    assert positions == sorted(positions)

    user.find(marker="include-uncleared").click()
    await user.should_see("Reconcile 5 transactions in 2 accounts")
    assert text(user, f"note-uncleared-{ORO}") == (
        "the bank has not taken these yet · reconcile them too"
    )


@pytest.mark.parametrize(
    ("typed", "expected", "primary"),
    [
        ("-150.00", "Matches", True),
        ("-150", "Matches", True),
        ("-174.90 €", "off by -24.90€", False),
        ("-1,150.00", "off by -1,000.00€", False),
    ],
    ids=["exact", "no-decimals", "symbol", "group-separator"],
)
async def test_the_bank_balance_is_checked_against_the_cleared_balance(
    user: User, seed: Seed, typed: str, expected: str, primary: bool
):
    seed()
    await open_reconcile(user)
    user.find(marker=f"toggle-{ORO}").click()
    user.find(marker=f"toggle-{CHECKING}").click()

    user.find(marker=f"bank-{ORO}").type(typed)

    await user.should_see(expected)
    assert ("primary" in classes(user, f"lock-{ORO}")) is primary
    assert "primary" not in classes(user, f"lock-{CHECKING}")


async def test_find_the_gap_highlights_the_transaction_that_explains_it(user: User, seed: Seed):
    seed()
    await open_reconcile(user)
    user.find(marker=f"bank-{ORO}").type("-174.90")
    await user.should_see("off by -24.90€")

    user.find(marker=f"gap-{ORO}").click()

    await user.should_see(marker="row-oro-zara")
    assert "gap" in classes(user, "row-oro-zara")
    assert "gap" not in classes(user, "row-oro-glovo")

    user.find(marker=f"bank-{ORO}").clear().type("-150")
    await user.should_see("Matches")
    assert "gap" not in classes(user, "row-oro-zara")


async def test_uncleared_rows_are_only_selectable_with_include_uncleared(user: User, seed: Seed):
    seed()
    await open_reconcile(user)
    user.find(marker=f"toggle-{ORO}").click()
    await user.should_see(marker="row-oro-zara")

    user.find(marker="row-oro-zara").click()
    await user.should_see("Reconcile 3 transactions in 2 accounts")
    await user.should_see("Uncleared rows are skipped", retries=5)

    user.find(marker="include-uncleared").click()
    await user.should_see("Reconcile 5 transactions in 2 accounts")
    await user.should_not_see("uncleared stay untouched")

    user.find(marker="row-oro-zara").click()
    await user.should_see("Reconcile 4 transactions in 2 accounts")
    assert text(user, f"lock-{ORO}") == "Reconcile 2 transactions"


async def test_lock_all_reconciles_exactly_the_selected_rows(
    user: User, seed: Seed, ynab_api: YnabClientStub, store_file: Path
):
    seed()
    await open_reconcile(user)
    user.find(marker=f"toggle-{CHECKING}").click()
    user.find(marker="row-chk-payroll").click()
    await user.should_see("Reconcile 2 transactions in 1 account")

    user.find(marker="lock-all").click()
    await user.should_see("Reconcile 2 transactions in 1 account?", retries=20)
    await user.should_see("💳 Oro · 2 transactions")
    assert text(user, "confirm-action") == "Reconcile 2"
    user.find(marker="confirm-action").click()

    await user.should_see("2 transactions reconciled", retries=20)
    assert updated(ynab_api) == {"oro-mercadona": RECONCILED, "oro-glovo": RECONCILED}
    # Payroll (31 Oct, cleared) was skipped: the next "since" scope must still show it. The
    # uncleared Zara (26 Oct) and gym could not be picked, so they do not hold it back
    assert LatestConfig.load().last_reconciliation_date == oct_(31)
    activity = Store(store_file).activity(state().require()[0].budget.id, kind="reconcile")
    assert [(a.kind, a.message, a.details) for a in activity] == [
        (
            "reconcile",
            "Reconciled 2 transactions in 1 account",
            {"count": 2, "accounts": [{"id": str(ORO), "name": "💳 Oro", "count": 2}]},
        )
    ]
    await user.should_see("2 transactions reconciled in YNAB")
    await user.should_see(marker="see-networth")
    user.find(marker=f"toggle-{ORO}").click()
    await user.should_see(marker="row-oro-glovo")
    assert "locked" in classes(user, "row-oro-glovo")
    assert "locked" not in classes(user, "row-oro-zara")
    # The reconciled rows moved to a section of their own; the card still lists all three
    await user.should_see(marker=f"section-reconciled-{ORO}")
    assert text(user, f"note-reconciled-{ORO}") == "already reconciled"
    assert text(user, f"note-cleared-{ORO}") == "the bank shows these · none"
    assert text(user, f"cleared-count-{ORO}") == "0"
    assert text(user, f"lock-{ORO}") == "Nothing to reconcile"
    user.find(marker=f"toggle-{ORO}").click()
    await user.should_see("Show 3 transactions")


async def test_an_uncleared_row_skipped_with_include_uncleared_on_holds_the_checkpoint(
    user: User, seed: Seed, ynab_api: YnabClientStub
):
    seed()
    await open_reconcile(user)
    user.find(marker="include-uncleared").click()
    await user.should_see("Reconcile 5 transactions in 2 accounts")
    user.find(marker=f"toggle-{ORO}").click()
    await user.should_see(marker="row-oro-zara")
    user.find(marker="row-oro-zara").click()
    await user.should_see("Reconcile 4 transactions in 2 accounts")

    user.find(marker="lock-all").click()
    await user.should_see(marker="confirm-action", retries=20)
    user.find(marker="confirm-action").click()

    await user.should_see("4 transactions reconciled", retries=20)
    assert "oro-zara" not in updated(ynab_api)
    assert LatestConfig.load().last_reconciliation_date == oct_(26)


async def test_locking_everything_moves_the_checkpoint_to_the_latest_locked_date(
    user: User, seed: Seed, ynab_api: YnabClientStub
):
    seed()
    await open_reconcile(user)
    user.find(marker="include-uncleared").click()
    await user.should_see("Reconcile 5 transactions in 2 accounts")

    user.find(marker="lock-all").click()
    await user.should_see(marker="confirm-action", retries=20)
    user.find(marker="confirm-action").click()

    await user.should_see("5 transactions reconciled", retries=20)
    # No grace days taken off: the "since" pill already starts a week before it
    assert LatestConfig.load().last_reconciliation_date == oct_(31)


async def test_the_account_lock_touches_only_that_account(
    user: User, seed: Seed, ynab_api: YnabClientStub
):
    seed()
    await open_reconcile(user)
    user.find(marker="include-uncleared").click()
    user.find(marker=f"toggle-{CHECKING}").click()
    user.find(marker=f"toggle-{ORO}").click()

    user.find(marker=f"lock-{CHECKING}").click()
    await user.should_see("1 of them is still uncleared", retries=20)
    user.find(marker="confirm-action").click()

    await user.should_see("2 transactions reconciled", retries=20)
    assert updated(ynab_api) == {"chk-payroll": RECONCILED, "chk-gym": RECONCILED}
    assert text(user, f"lock-{ORO}") == "Reconcile 3 transactions"
    await user.should_see(marker="lock-more")


async def test_cancelling_the_confirmation_changes_nothing(
    user: User, seed: Seed, ynab_api: YnabClientStub
):
    seed()
    await open_reconcile(user)

    user.find(marker="lock-all").click()
    await user.should_see(marker="confirm-cancel", retries=20)
    user.find(marker="confirm-cancel").click()

    await user.should_see("Reconcile 3 transactions in 2 accounts")
    ynab_api.api("transactions").update_transactions.assert_not_called()
    assert LatestConfig.load().last_reconciliation_date is None


async def test_a_failed_lock_keeps_everything_as_it_was(
    user: User, seed: Seed, ynab_api: YnabClientStub, store_file: Path
):
    seed()
    ynab_api.api("transactions").update_transactions.side_effect = ApiException(
        status=500, reason="Internal Server Error"
    )
    await open_reconcile(user)

    user.find(marker="lock-all").click()
    await user.should_see(marker="confirm-action", retries=20)
    user.find(marker="confirm-action").click()

    await user.should_see("Nothing was reconciled. YNAB answered 500", retries=20)
    await user.should_see("Reconcile 3 transactions in 2 accounts")
    assert LatestConfig.load().last_reconciliation_date is None
    assert Store(store_file).activity(state().require()[0].budget.id, kind="reconcile") == []


async def test_a_lock_that_timed_out_says_ynab_may_have_applied_it_and_syncs_to_check(
    user: User, seed: Seed, ynab_api: YnabClientStub, mocker: MockerFixture
):
    seed()
    ynab_api.api("transactions").update_transactions.side_effect = MaxRetryError(
        pool=None,  # type: ignore[arg-type]
        url="/transactions",
        reason=ReadTimeoutError(None, "/transactions", "Read timed out."),  # type: ignore[arg-type]
    )
    await open_reconcile(user)
    invalidate = mocker.spy(AppState, "invalidate")

    user.find(marker="lock-all").click()
    await user.should_see(marker="confirm-action", retries=20)
    user.find(marker="confirm-action").click()

    await user.should_see(LOCK_TIMED_OUT, retries=20)
    await user.should_not_see("Nothing was reconciled")
    invalidate.assert_called()


async def test_a_failed_settings_save_after_the_lock_still_logs_syncs_and_frees_the_view(
    user: User, seed: Seed, ynab_api: YnabClientStub, store_file: Path, mocker: MockerFixture
):
    seed()
    await open_reconcile(user)
    invalidate = mocker.spy(AppState, "invalidate")
    mocker.patch.object(LatestConfig, "save", side_effect=OSError("No space left on device"))

    user.find(marker="lock-all").click()
    await user.should_see(marker="confirm-action", retries=20)
    user.find(marker="confirm-action").click()

    # YNAB already changed: the view says so, logs it and syncs, and can be used again
    await user.should_see(SAVE_FAILED, retries=20)
    await user.should_see("3 transactions reconciled", retries=20)
    invalidate.assert_called()
    activity = Store(store_file).activity(state().require()[0].budget.id, kind="reconcile")
    assert [a.message for a in activity] == ["Reconciled 3 transactions in 2 accounts"]
    await user.should_see(marker="see-networth")
    await user.should_not_see("Reconciling 3 transactions in YNAB…")


async def test_the_since_scope_starts_a_week_before_the_last_reconciliation(
    config_v4: LatestConfig, user: User, seed: Seed
):
    config_v4.last_reconciliation_date = oct_(31)
    config_v4.save()
    state().reload()
    seed()
    await open_reconcile(user)

    await user.should_see("since 24 Oct")
    await user.should_see("2 accounts · 4 transactions not reconciled")
    # Glovo (22 Oct) is out of scope: the counts follow the chips
    assert text(user, f"cleared-count-{ORO}") == "1"
    assert text(user, f"toggle-{ORO}") == "Show 2 transactions"

    user.find(marker="scope-all").click()
    await user.should_see("2 accounts · 5 transactions not reconciled")
    assert text(user, f"cleared-count-{ORO}") == "2"
    assert text(user, f"toggle-{ORO}") == "Show 3 transactions"


async def test_an_empty_section_still_says_what_it_means(
    config_v4: LatestConfig, user: User, seed: Seed
):
    config_v4.last_reconciliation_date = oct_(31)
    config_v4.save()
    state().reload()
    seed(transactions=[t for t in TRANSACTIONS if t.id != "chk-payroll"])
    await open_reconcile(user)
    user.find(marker=f"toggle-{CHECKING}").click()

    await user.should_see(marker=f"section-cleared-{CHECKING}")
    assert text(user, f"note-cleared-{CHECKING}") == "the bank shows these · none since 24 Oct"
    assert text(user, f"cleared-count-{CHECKING}") == "0"
    assert text(user, f"lock-{CHECKING}") == "Nothing to reconcile"

    user.find(marker="scope-all").click()
    await user.should_see("2 accounts · 4 transactions not reconciled")
    user.find(marker=f"toggle-{CHECKING}").click()
    assert text(user, f"note-cleared-{CHECKING}") == "the bank shows these · none"


async def test_nothing_to_reconcile_shows_the_empty_state(user: User, seed: Seed):
    seed(transactions=[tx("oro-done", ORO, oct_(20), -5_000, RECONCILED)])
    await user.open("/reconcile")

    await user.should_see("All accounts are reconciled", retries=20)
    await user.should_not_see(marker="lock-all")


async def test_a_stale_store_is_synced_before_showing_anything(
    user: User, seed: Seed, ynab_api: YnabClientStub
):
    seed(fresh=False)
    await open_reconcile(user)

    await user.should_see("2 accounts · 5 transactions not reconciled")
    ynab_api.api("transactions").get_transactions.assert_called()


async def test_a_store_synced_a_moment_ago_is_synced_again_when_the_view_opens(
    user: User, seed: Seed, ynab_api: YnabClientStub
):
    # A match or a delete made in YNAB since must not show up as a transaction to lock
    seed(fresh=True)
    ynab_api.api("transactions").get_transactions.reset_mock()

    await open_reconcile(user)

    await user.should_see("2 accounts · 5 transactions not reconciled")
    ynab_api.api("transactions").get_transactions.assert_called()


async def test_a_failed_sync_shows_the_last_copy_and_says_so(
    user: User, seed: Seed, ynab_api: YnabClientStub
):
    seed(fresh=True)
    ynab_api.api("transactions").get_transactions.side_effect = ApiException(
        status=500, reason="Internal Server Error"
    )

    await open_reconcile(user)

    await user.should_see("Showing the last sync", retries=20)
    await user.should_see("2 accounts · 5 transactions not reconciled")


def stored(id_: str, amount: int, cleared: TransactionClearedStatus) -> StoredTransaction:
    return StoredTransaction(
        id=id_,
        account_id=str(ORO),
        date=oct_(1),
        amount=amount,
        cleared=cleared,
        approved=True,
        deleted=False,
        payee_name=None,
        category_name=None,
        import_id=None,
        memo=None,
        transfer_account_id=None,
    )


@pytest.mark.parametrize(
    ("difference", "expected"),
    [
        (-24_900, {"zara"}),
        (64_120, {"mercadona"}),
        (-64_120, set()),
        (-43_300, {"zara", "glovo"}),
        (1, set()),
        (0, set()),
    ],
    ids=["uncleared-bank-took-it", "cleared-bank-has-not", "wrong-sign", "pair", "none", "zero"],
)
def test_gap_candidates(difference: int, expected: set[str]):
    transactions = [
        stored("mercadona", -64_120, CLEARED),
        stored("zara", -24_900, UNCLEARED),
        stored("glovo", 18_400, CLEARED),
    ]

    assert gap_candidates(transactions, difference) == expected


@pytest.mark.parametrize(
    ("count", "since", "included", "cleared", "uncleared"),
    [
        (2, "29 Oct", False, "2 to reconcile", "skipped"),
        (1, None, True, "1 to reconcile", "reconcile them too"),
        (0, "29 Oct", False, "none since 29 Oct", "none since 29 Oct"),
        (0, None, True, "none", "none"),
    ],
    ids=["since", "all-time-included", "none-since", "none-all-time"],
)
def test_section_notes_say_what_the_status_means_and_what_is_left(
    count: int, since: str | None, included: bool, cleared: str, uncleared: str
):
    assert cleared_note(count, since) == f"the bank shows these · {cleared}"
    assert uncleared_note(count, since, included=included) == (
        f"the bank has not taken these yet · {uncleared}"
    )


def test_the_card_buttons_say_reconcile():
    assert show_label(1) == "Show 1 transaction"
    assert reconcile_label(3) == "Reconcile 3 transactions"
    assert reconcile_label(0) == "Nothing to reconcile"


def test_the_confirmation_says_reconcile():
    oro = StoredAccount(
        id=str(ORO),
        name="💳 Oro",
        type="creditCard",
        closed=False,
        on_budget=True,
        balance=0,
        cleared_balance=0,
        uncleared_balance=0,
    )

    title, lines, action = lock_confirmation([(oro, [stored("zara", -24_900, UNCLEARED)])])

    assert (title, action) == ("Reconcile 1 transaction in 1 account?", "Reconcile 1")
    assert lines[-2:] == ["1 of them is still uncleared", "They are marked reconciled in YNAB."]
