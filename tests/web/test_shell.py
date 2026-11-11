import datetime as dt
import gc
import threading
from pathlib import Path

import pytest
from nicegui import ui
from nicegui.elements.upload_files import SmallFileUpload
from nicegui.testing.user import User
from pytest_mock import MockerFixture
from ynab import ApiException

from tests.factories import AccountFactory, TransactionDetailFactory
from tests.helpers.web import arrived, record_threads
from tests.helpers.ynab_api import YnabClientStub
from ynab_unlinked.config import LatestConfig
from ynab_unlinked.store import Store
from ynab_unlinked.web import shell
from ynab_unlinked.web.state import state

NOW = dt.datetime(2026, 11, 3, 12, 0, tzinfo=dt.UTC)


@pytest.mark.parametrize(
    ("last", "expected"),
    [
        (None, "not synced yet"),
        (NOW - dt.timedelta(seconds=59), "synced just now"),
        (NOW - dt.timedelta(minutes=2, seconds=59), "synced 2 min ago"),
        (NOW - dt.timedelta(hours=3), "synced 3 h ago"),
        (NOW - dt.timedelta(days=1), "synced 1 day ago"),
        (NOW - dt.timedelta(days=9), "synced 9 days ago"),
        # A clock that moved backwards must not print a negative age
        (NOW + dt.timedelta(minutes=5), "synced just now"),
    ],
    ids=["never", "seconds", "minutes", "hours", "one-day", "days", "future"],
)
def test_sync_label(last: dt.datetime | None, expected: str):
    assert shell.sync_label(last, NOW) == expected


@pytest.mark.version("missing")
@pytest.mark.parametrize("path", ["/", "/settings", "/import"])
async def test_every_page_sends_to_onboarding_until_configured(user: User, path: str):
    await user.open(path)

    await user.should_see("Connect to YNAB")
    await user.should_not_see(marker="nav-home")


@pytest.mark.version("V4")
async def test_onboarding_sends_home_once_configured(user: User):
    await user.open("/onboarding")

    await user.should_see(marker="nav-home")
    await user.should_not_see("Connect to YNAB")


@pytest.mark.version("V4")
async def test_the_sidebar_navigates_between_views(user: User):
    await user.open("/")

    user.find(marker="nav-reconcile").click()

    await user.should_see("Reconcile what the bank confirmed")
    await arrived(user, "/reconcile")


@pytest.mark.version("V4")
async def test_the_finance_pages_sit_under_one_heading(user: User):
    await user.open("/")

    # Elements get increasing ids in the order they are drawn
    order = [
        user.find(marker=marker).elements.pop().id
        for marker in (
            "nav-reconcile",
            "nav-group-finances",
            "nav-networth",
            "nav-cashflow",
            "nav-spending",
            "nav-settings",
        )
    ]
    assert order == sorted(order)


@pytest.mark.version("V4")
async def test_files_dropped_anywhere_reach_the_import_view(user: User):
    await user.open("/reconcile")
    upload = user.find(marker="drop-upload").elements.pop()
    assert isinstance(upload, ui.upload)

    statement = SmallFileUpload(name="movimientos.txt", content_type="text/plain", _data=b"x")
    await upload.handle_uploads([statement])

    await user.should_see("movimientos.txt", marker="file-1", retries=20)


@pytest.mark.version("V4")
async def test_files_dropped_on_the_import_view_go_to_its_handler(user: User):
    await user.open("/import")
    await user.should_see("Files → Review → Done")
    upload = user.find(marker="drop-upload").elements.pop()
    assert isinstance(upload, ui.upload)

    statement = SmallFileUpload(name="tarjeta.xlsx", content_type="application/xlsx", _data=b"x")
    await upload.handle_uploads([statement])

    await user.should_see("tarjeta.xlsx", marker="file-1", retries=20)
    with user:
        assert shell.pending_uploads() == []


@pytest.mark.version("V4")
async def test_the_sync_chip_syncs_the_store_and_says_when(
    user: User, ynab_api: YnabClientStub, store_file: Path
):
    response = ynab_api.api("transactions").get_transactions.return_value
    response.data.transactions = [TransactionDetailFactory()]
    response.data.server_knowledge = 7
    ynab_api.api("accounts").get_accounts.return_value.data.accounts = [AccountFactory()]
    await user.open("/")
    await user.should_see("not synced yet")
    await user.should_see("Not synced with YNAB yet")

    user.find(marker="sync-chip").click()

    await user.should_see("1 transaction loaded from YNAB", retries=20)
    await user.should_see("synced just now")
    # Home shows the store, so it is rendered again with what the sync brought
    await user.should_not_see("Not synced with YNAB yet")
    budget_id = state().require()[0].budget.id
    assert Store(store_file).accounts(budget_id)[0].name == "Checking"
    assert [(a.kind, a.message, a.details) for a in Store(store_file).activity(budget_id)] == [
        ("sync", "Synced · 1 change from YNAB", {"changes": 1, "full": True})
    ]


@pytest.mark.version("V4")
async def test_a_sync_that_brings_nothing_is_not_logged(
    user: User, ynab_api: YnabClientStub, store_file: Path
):
    response = ynab_api.api("transactions").get_transactions.return_value
    response.data.transactions = []
    response.data.server_knowledge = 7
    ynab_api.api("accounts").get_accounts.return_value.data.accounts = []
    budget_id = state().require()[0].budget.id
    # Known server knowledge, so this is a delta sync
    Store(store_file).sync(state().require()[1], budget_id)
    await user.open("/settings")

    user.find(marker="sync-chip").click()

    await user.should_see("0 changes pulled from YNAB", retries=20)
    assert Store(store_file).activity(budget_id) == []


@pytest.mark.version("V4")
async def test_a_sync_that_removes_merged_ghosts_says_so_in_the_log(
    user: User, ynab_api: YnabClientStub, store_file: Path
):
    api = ynab_api.api("transactions")
    api.get_transactions.return_value.data.transactions = [
        TransactionDetailFactory(id="imported", import_id="YNAB:-12900:2026-11-01:1"),
        TransactionDetailFactory(id="manual", import_id="YNAB:-12900:2026-11-01:1"),
    ]
    api.get_transactions.return_value.data.server_knowledge = 7
    ynab_api.api("accounts").get_accounts.return_value.data.accounts = []
    budget_id = state().require()[0].budget.id
    # Both exist at first: a match the user has not approved yet
    Store(store_file).sync(state().require()[1], budget_id)
    # The user approves the match: the delta brings the manual one, the import is gone
    api.get_transactions.return_value.data.transactions = [
        TransactionDetailFactory(id="manual", import_id="YNAB:-12900:2026-11-01:1"),
    ]

    def get_transaction_by_id(plan_id: str, transaction_id: str) -> None:
        if transaction_id == "imported":
            raise ApiException(status=404)

    api.get_transaction_by_id.side_effect = get_transaction_by_id
    await user.open("/settings")

    user.find(marker="sync-chip").click()

    await user.should_see("1 change pulled from YNAB", retries=20)
    assert [(a.message, a.details) for a in Store(store_file).activity(budget_id)] == [
        (
            "Synced · 1 change from YNAB · 1 stale removed",
            {"changes": 1, "full": False, "ghosts": 1},
        )
    ]


@pytest.mark.version("V4")
async def test_a_sync_from_the_chip_leaves_the_import_view_alone(
    user: User, ynab_api: YnabClientStub
):
    response = ynab_api.api("transactions").get_transactions.return_value
    response.data.transactions = [TransactionDetailFactory()]
    response.data.server_knowledge = 7
    ynab_api.api("accounts").get_accounts.return_value.data.accounts = [AccountFactory()]
    await user.open("/import")
    upload = user.find(marker="drop-upload").elements.pop()
    assert isinstance(upload, ui.upload)
    statement = SmallFileUpload(name="tarjeta.xlsx", content_type="application/xlsx", _data=b"x")
    await upload.handle_uploads([statement])
    await user.should_see("tarjeta.xlsx", marker="file-1", retries=20)

    user.find(marker="sync-chip").click()

    await user.should_see("1 transaction loaded from YNAB", retries=20)
    await user.should_see("tarjeta.xlsx", marker="file-1")


@pytest.mark.version("V4")
async def test_a_config_save_runs_off_the_event_loop(user: User, mocker: MockerFixture):
    """The file and the keychain can block: every view saves through here, and a save on the
    event loop would freeze every open page."""
    threads = record_threads(mocker, LatestConfig, "save")
    await user.open("/")

    assert await shell.save_config(lambda config: None)

    assert threads
    assert threading.main_thread().name not in threads


@pytest.mark.version("V4")
async def test_a_toast_after_an_await_survives_its_element_being_redrawn(user: User):
    # A click on a card starts a save; while it waits, another handler redraws the card and
    # the clicked element is gone. Its toast must still reach the page, and the handler go on.
    await user.open("/")
    await user.should_see(marker="nav-home")
    page = user.find(marker="nav-home").elements.pop().parent_slot
    assert page is not None
    with page:
        box = ui.element("div")
        with box:
            handler_slot = ui.label("redrawn").default_slot
    box.clear()  # the redraw: nothing holds the element the handler runs in any more
    gc.collect()

    with page, handler_slot:
        shell.notify("Accounts saved")

    await user.should_see("Accounts saved")
