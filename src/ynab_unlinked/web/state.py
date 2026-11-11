"""What every page of the app shares: the config, the YNAB client, the store and the loaders.

There is one `AppState` per process, reached through `state()`. Views read from it and save
the config through `update_config()`, which keeps changes another process (the CLI) saved.

Every sync runs as the one shared `_sync_task`: `sync()` joins it, `invalidate()` during it asks
for one more round when it ends, and `resync()` and `reset()` wait for it before starting from
scratch or deleting everything.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
from collections.abc import Callable
from pathlib import Path

from nicegui import background_tasks, run
from pydantic import ValidationError

from ynab_unlinked.config import LatestConfig, edit_config, get_config
from ynab_unlinked.config.core import ConfigError
from ynab_unlinked.core.progress import NullProgress, Progress
from ynab_unlinked.entities.registry import LoaderSpec, loaders
from ynab_unlinked.formatter import Formatter
from ynab_unlinked.local_data import delete_local_data
from ynab_unlinked.store import Store, StoredAccount, StoreError, SyncResult, store_path
from ynab_unlinked.web.wording import YNAB_TIMED_OUT, plural
from ynab_unlinked.web.ynab import stored_accounts
from ynab_unlinked.ynab_api import Client
from ynab_unlinked.ynab_api.errors import timed_out

logger = logging.getLogger(__name__)

TOKEN_LOST = "Your YNAB token is no longer in the keychain."

AUTO_SYNC_AFTER = dt.timedelta(minutes=10)
"""How old the budget copy may get while the app is open before it syncs on its own."""

_NO_PROGRESS = NullProgress()


class NotConfiguredError(RuntimeError):
    def __init__(self) -> None:
        super().__init__("yul is not configured yet")


class AppState:
    def __init__(self) -> None:
        self.config: LatestConfig | None = None
        self.client: Client | None = None
        self.formatter: Formatter | None = None
        self.loaders: list[LoaderSpec] = []
        self.last_sync: dt.datetime | None = None
        self.load_error: str | None = None
        """Why the config on disk could not be read, shown by onboarding before replacing it."""
        self.token_lost: LatestConfig | None = None
        """A config whose token left the keychain: onboarding asks for the token, keeps the rest."""
        self.sync_error: str | None = None
        self.data_version = 0
        """Goes up each time a sync changes the budget copy: pages drawn from an older one are
        behind (the shell draws them again)."""
        self._sync_attempt: dt.datetime | None = None
        """When the last sync started, so a failing one is not retried at every look."""
        self._store: Store | None = None
        self._sync_task: asyncio.Task[SyncResult] | None = None
        self._written = False
        """Something was written to YNAB since the current sync round started, if any: the
        store lags behind until the next round."""

    @property
    def store(self) -> Store:
        """The local store, opened (and created) on first use.

        Opening it sets up the file and runs its migrations, which can wait for the CLI: the
        state's own calls open it off the event loop (`app.run()` before the server starts,
        then inside each `run.io_bound` call), so views find it open.
        """
        if self._store is None:
            self._store = Store(store_path())
        return self._store

    @property
    def configured(self) -> bool:
        return self.config is not None

    @property
    def syncing(self) -> bool:
        return self._sync_task is not None and not self._sync_task.done()

    def require(self) -> tuple[LatestConfig, Client]:
        """The config and client, for code that only runs once yul is configured."""
        if self.config is None or self.client is None:
            raise NotConfiguredError()
        return self.config, self.client

    def require_formatter(self) -> Formatter:
        """The budget's formatter, for code that only runs once yul is configured."""
        if self.formatter is None:
            raise NotConfiguredError()
        return self.formatter

    def load(self) -> None:
        """Read the config from disk and rebuild everything that depends on it.

        Also forgets the open store, for when its file may have been deleted.
        """
        self._store = None
        self._read_config()

    def reload(self) -> None:
        """Pick up a config that was just saved, keeping the open store.

        Reads the store for the time of the last sync, so it blocks: the app runs it off the
        event loop.
        """
        self._read_config()

    def _read_config(self) -> None:
        self.loaders = loaders()
        self.load_error = None
        self.token_lost = None
        try:
            config = get_config()
        except (ConfigError, ValidationError, ValueError, OSError) as error:
            logger.warning("The yul config could not be read: %s", error)
            self.load_error = str(error)
            config = None
        if config is not None and not config.api_key:
            self.load_error = TOKEN_LOST
            self.token_lost = config
            config = None

        self.config = config
        if config is None:
            self.client = None
            self.formatter = None
            self.last_sync = None
            return

        self.client = Client(config.api_key)
        self.formatter = Formatter(
            date_format=config.budget.date_format,
            currency_format=config.budget.currency_format,
        )
        try:
            self.last_sync = self.store.last_sync(config.budget.id)
        except StoreError as error:
            self.last_sync = None
            self.sync_error = str(error)

    def update_config(self, change: Callable[[LatestConfig], None]) -> LatestConfig:
        """Apply `change` to the config on disk, save it and reload; returns the saved config.

        The file is read again first, so what the CLI saved while the app was open (a bank's
        account, the last reconciliation) survives a save from the app.

        Without a file it raises `ConfigError` and loads the state again, which drops the
        app to onboarding: `yul config reset` ran while the app was open, and a save must
        not bring the config and the token back.

        It blocks on the disk and the keychain: views call it through `shell.save_config`,
        which runs it off the event loop. Nothing is saved when `change` raises.
        """
        if self.config is None and not LatestConfig.exists():
            raise NotConfiguredError()
        try:
            with edit_config() as config:
                change(config)
        except ConfigError:
            self.load()
            raise
        self.reload()
        return config

    async def sync(self, progress: Progress = _NO_PROGRESS) -> SyncResult:
        """Bring the store up to date with YNAB. Concurrent callers share the running sync."""
        if self._sync_task is None or self._sync_task.done():
            self._sync_task = asyncio.ensure_future(self._sync_rounds(progress))
        return await asyncio.shield(self._sync_task)

    async def resync(self, progress: Progress = _NO_PROGRESS) -> SyncResult:
        """Forget the budget's copy (not the activity log) and fetch all of it again.

        Waits for a running sync first, so its delta cannot land in the emptied copy, and
        then runs as the shared sync task: a `sync()` meanwhile joins it.
        """
        self.require()
        await self._sync_ended()
        self._sync_task = asyncio.ensure_future(self._resync(progress))
        return await asyncio.shield(self._sync_task)

    async def reset(self, paths: list[Path]) -> None:
        """Delete `paths` and the token (`delete_local_data`), then load the empty state.

        Waits for a running sync first, so it cannot write the deleted budget back into a
        new copy, and forgets the config before deleting so no other sync starts meanwhile.
        """
        await self._sync_ended()
        self.config = None
        self.client = None
        try:
            await run.io_bound(delete_local_data, paths)
        finally:
            # The budget copy is gone too: load() opens a new one, off the event loop. Also
            # after a failed delete, so the app reads again whatever is left instead of nothing
            await run.io_bound(self.load)

    async def _sync_ended(self) -> None:
        while self._sync_task is not None and not self._sync_task.done():
            # wait() never raises: how the running sync ended is its callers' business
            await asyncio.wait({self._sync_task})

    async def _resync(self, progress: Progress) -> SyncResult:
        config, _ = self.require()
        await run.io_bound(lambda: self.store.clear(config.budget.id))
        return await self._sync_rounds(progress)

    async def _sync_rounds(self, progress: Progress) -> SyncResult:
        """Sync, and once more each time `invalidate()` was called while syncing."""
        while True:
            self._written = False
            result = await self._sync(progress)
            if not self._written:
                return result

    def invalidate(self) -> None:
        """Call after writing to YNAB: the next view that needs fresh data syncs first.

        Starts the sync right away too, so it is usually done before the user gets there. A
        sync already running may have fetched before the write: one more round runs after it.
        """
        self._written = True
        self.sync_in_background()

    def sync_if_stale(self, now: dt.datetime | None = None) -> bool:
        """Start a background sync when the copy is older than `AUTO_SYNC_AFTER`.

        Only once a first sync brought the budget (the pages run that one themselves), and at
        most once per `AUTO_SYNC_AFTER`, also when the last one failed. Returns whether it
        started one.
        """
        if not self.configured or self.syncing or self.last_sync is None:
            return False
        now = now or dt.datetime.now(dt.UTC)
        latest = max(self.last_sync, self._sync_attempt or self.last_sync)
        if now - latest < AUTO_SYNC_AFTER:
            return False
        self.sync_in_background()
        return True

    async def _sync(self, progress: Progress) -> SyncResult:
        config, client = self.require()
        self._sync_attempt = dt.datetime.now(dt.UTC)
        try:
            # In the worker: the first use opens the store, which must not block the loop
            result = await run.io_bound(lambda: self.store.sync(client, config.budget.id, progress))
        except Exception as error:
            # A stalled YNAB gives up after `REQUEST_TIMEOUT`, in the user's words
            self.sync_error = YNAB_TIMED_OUT if timed_out(error) else str(error)
            raise
        self.sync_error = None
        self.last_sync = await run.io_bound(lambda: self.store.last_sync(config.budget.id))
        # A sync that brought nothing is not worth a line in the feed (one runs at every start)
        if result.full or result.transactions_changed or result.ghosts_removed:
            changes = result.transactions_changed
            ghosts = result.ghosts_removed
            message = f"Synced · {plural(changes, 'change')} from YNAB"
            details: dict[str, int | bool] = {"changes": changes, "full": result.full}
            if ghosts:
                message += f" · {ghosts} stale removed"
                details["ghosts"] = ghosts
            await run.io_bound(self.store.log, config.budget.id, "sync", message, details)
            self.data_version += 1
        return result

    def sync_in_background(self) -> None:
        """Start a sync nobody waits for. Failures are logged and shown by the sync chip."""
        if not self.configured or self.syncing:
            return

        async def sync_logged() -> None:
            try:
                await self.sync()
            except Exception as error:
                logger.warning("Background sync with YNAB failed: %s", error)

        # NiceGUI returns the task as a bare `asyncio.Task`
        background_tasks.create(sync_logged(), name="yul store sync")  # pyright: ignore[reportUnknownMemberType]

    async def budget_accounts(self) -> list[StoredAccount]:
        """Every account of the budget, from the store once synced, from YNAB before that."""
        config, client = self.require()
        if stored := await run.io_bound(lambda: self.store.accounts(config.budget.id)):
            return stored

        return stored_accounts(await run.io_bound(client.accounts, config.budget.id) or [])


_state: AppState | None = None


def state() -> AppState:
    """The state shared by every page of this process, loaded on first use."""
    global _state
    if _state is None:
        _state = AppState()
        _state.load()
    return _state
