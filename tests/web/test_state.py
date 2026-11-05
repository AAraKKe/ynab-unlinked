import asyncio
import datetime as dt
import threading
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from pytest_mock import MockerFixture
from urllib3.exceptions import MaxRetryError, ReadTimeoutError
from ynab import TransactionsResponse, TransactionsResponseData

from tests.factories import TransactionDetailFactory
from tests.helpers.config import ConfigFiles
from tests.helpers.ynab_api import YnabClientStub
from ynab_unlinked.config import LatestConfig
from ynab_unlinked.store import Store
from ynab_unlinked.web.state import AppState, NotConfiguredError
from ynab_unlinked.web.wording import YNAB_TIMED_OUT
from ynab_unlinked.ynab_api import Client

pytestmark = pytest.mark.version("V4")


def response(ids: list[str], knowledge: int) -> TransactionsResponse:
    return TransactionsResponse(
        data=TransactionsResponseData(
            transactions=[TransactionDetailFactory(id=id) for id in ids],
            server_knowledge=knowledge,
        )
    )


class Ynab:
    """YNAB holding `full` for a full fetch, `delta` for a delta. Deltas wait for `release`."""

    def __init__(self, ynab_api: YnabClientStub, full: list[str], delta: list[str]) -> None:
        self.full = full
        self.delta = delta
        self.release = threading.Event()
        self.waiting = threading.Event()
        self.calls: list[str] = []
        ynab_api.api("accounts").get_accounts.return_value.data.accounts = []
        ynab_api.api("transactions").get_transactions.side_effect = self.get_transactions

    def get_transactions(self, plan_id: str, **kwargs: object) -> TransactionsResponse:
        if "last_knowledge_of_server" in kwargs:
            self.calls.append("delta")
            self.waiting.set()
            assert self.release.wait(5), "the test never released the delta"
            return response(self.delta, 20)
        self.calls.append("full")
        return response(self.full, 30)

    async def blocked(self) -> None:
        """Wait until a delta sync is inside YNAB."""
        for _ in range(250):
            if self.waiting.is_set():
                return
            await asyncio.sleep(0.02)
        raise AssertionError("no delta sync started")


@pytest.fixture
def app_state(config_v4: LatestConfig, ynab_api: YnabClientStub, store_file: Path) -> AppState:
    """A loaded state whose store already holds t1 and t2 at knowledge 10."""
    ynab_api.api("transactions").get_transactions.return_value = response(["t1", "t2"], 10)
    ynab_api.api("accounts").get_accounts.return_value.data.accounts = []
    Store(store_file).sync(Client("api-key"), config_v4.budget.id)
    current = AppState()
    current.load()
    return current


def stored_ids(current: AppState) -> list[str]:
    config, _ = current.require()
    return [t.id for t in current.store.transactions(config.budget.id)]


async def test_a_resync_while_a_sync_runs_waits_for_it_and_loses_no_rows(
    app_state: AppState, ynab_api: YnabClientStub
):
    ynab = Ynab(ynab_api, full=["t1", "t2", "t3"], delta=["t3"])
    running = asyncio.ensure_future(app_state.sync())
    await ynab.blocked()

    resync = asyncio.ensure_future(app_state.resync())
    await asyncio.sleep(0.05)
    ynab.release.set()
    await running
    result = await resync

    assert result is not None and result.full
    assert ynab.calls == ["delta", "full"]
    assert stored_ids(app_state) == ["t1", "t2", "t3"]


async def test_a_reset_while_a_sync_runs_waits_for_it_before_deleting(
    app_state: AppState, ynab_api: YnabClientStub, store_file: Path, mocker: MockerFixture
):
    ynab = Ynab(ynab_api, full=[], delta=["t3"])
    running = asyncio.ensure_future(app_state.sync())
    await ynab.blocked()
    deleted_while_syncing: list[bool] = []
    delete = mocker.patch(
        "ynab_unlinked.web.state.delete_local_data",
        side_effect=lambda paths: deleted_while_syncing.append(not running.done()),
    )

    reset = asyncio.ensure_future(app_state.reset([store_file]))
    await asyncio.sleep(0.05)
    assert not delete.called
    ynab.release.set()
    await running
    await reset

    delete.assert_called_once_with([store_file])
    assert deleted_while_syncing == [False]


async def test_a_reset_deletes_the_budget_copy_and_forgets_the_config(
    app_state: AppState, store_file: Path, config_files: ConfigFiles
):
    await app_state.reset([store_file, config_files.v2.parent])

    assert not store_file.exists()
    assert not app_state.configured
    app_state.sync_in_background()
    assert not app_state.syncing


async def test_a_resync_that_ynab_never_answers_gives_up_and_lets_a_reset_run(
    app_state: AppState, ynab_api: YnabClientStub, store_file: Path
):
    # What the client raises once `REQUEST_TIMEOUT` passed with no answer
    ynab_api.api("transactions").get_transactions.side_effect = MaxRetryError(
        pool=None,  # type: ignore[arg-type]
        url="/plans/budget/transactions",
        reason=ReadTimeoutError(None, "/transactions", "Read timed out."),  # type: ignore[arg-type]
    )

    with pytest.raises(MaxRetryError):
        await asyncio.wait_for(app_state.resync(), 5)

    assert not app_state.syncing
    assert app_state.sync_error == YNAB_TIMED_OUT
    # The reset waits for the sync: it would hang forever if the sync never ended
    await asyncio.wait_for(app_state.reset([store_file]), 5)


async def test_a_sync_during_a_resync_joins_it(app_state: AppState, ynab_api: YnabClientStub):
    ynab = Ynab(ynab_api, full=["t1", "t2"], delta=[])

    resync = asyncio.ensure_future(app_state.resync())
    await asyncio.sleep(0)
    joined = await app_state.sync()

    assert joined == await resync
    assert ynab.calls == ["full"]


async def test_the_activity_log_survives_a_resync(app_state: AppState, ynab_api: YnabClientStub):
    Ynab(ynab_api, full=["t1"], delta=[])
    config, _ = app_state.require()
    app_state.store.log(config.budget.id, "import", "Imported 3 transactions")

    await app_state.resync()

    messages = [a.message for a in app_state.store.activity(config.budget.id)]
    assert "Imported 3 transactions" in messages
    assert stored_ids(app_state) == ["t1"]


async def test_a_write_during_a_sync_runs_one_more_sync_after_it(
    app_state: AppState, ynab_api: YnabClientStub, mocker: MockerFixture
):
    ynab = Ynab(ynab_api, full=[], delta=["t3"])
    background = mocker.patch.object(AppState, "sync_in_background")
    running = asyncio.ensure_future(app_state.sync())
    await ynab.blocked()

    app_state.invalidate()
    ynab.release.set()
    await running

    assert ynab.calls == ["delta", "delta"]
    assert not app_state.stale
    background.assert_called_once()


async def test_without_a_write_a_sync_runs_once(app_state: AppState, ynab_api: YnabClientStub):
    ynab = Ynab(ynab_api, full=[], delta=[])
    ynab.release.set()

    await app_state.sync()

    assert ynab.calls == ["delta"]


def test_banks_are_discovered_once(app_state: AppState, mocker: MockerFixture):
    discover = mocker.patch("ynab_unlinked.web.state.loaders", return_value=[MagicMock()])
    app_state.loaders = []

    app_state.reload()
    app_state.reload()
    app_state.load()

    discover.assert_called_once()


def test_a_reload_for_the_same_budget_reads_no_database(app_state: AppState, mocker: MockerFixture):
    last_sync = mocker.spy(Store, "last_sync")

    app_state.reload()

    last_sync.assert_not_called()
    assert app_state.last_sync is not None


def test_update_config_applies_the_change_to_the_file_not_to_the_old_copy(config: str):
    app = AppState()
    app.load()
    cli = LatestConfig.load()
    cli.last_reconciliation_date = dt.date(2025, 5, 10)
    cli.save()

    def change(config: LatestConfig) -> None:
        config.adjustments.payee = "Set by the app"

    saved = app.update_config(change)

    on_disk = LatestConfig.load()
    assert on_disk.last_reconciliation_date == dt.date(2025, 5, 10)
    assert on_disk.adjustments.payee == "Set by the app"
    assert saved == on_disk
    assert app.config == on_disk


@pytest.mark.version("missing")
def test_update_config_without_any_config_is_an_error(config: str, config_files: ConfigFiles):
    app = AppState()
    app.load()

    with pytest.raises(NotConfiguredError):
        app.update_config(lambda config: None)
    assert not config_files.path("V4").exists()
