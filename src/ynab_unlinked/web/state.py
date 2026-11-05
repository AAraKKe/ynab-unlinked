"""What every page of the app shares: the config, the YNAB client, the store and the loaders.

There is one `AppState` per process, reached through `state()`. Views read from it and call
`reload()` after they save the config, so the next page sees the change.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import logging

from nicegui import background_tasks, run
from pydantic import ValidationError
from ynab import AccountType

from ynab_unlinked.buckets import Bucket, bucket_for
from ynab_unlinked.config import LatestConfig, get_config
from ynab_unlinked.config.core import ConfigError
from ynab_unlinked.core.progress import NullProgress, Progress
from ynab_unlinked.entities.registry import LoaderSpec, loaders
from ynab_unlinked.formatter import Formatter
from ynab_unlinked.store import Store, StoredAccount, StoreError, SyncResult, store_path
from ynab_unlinked.ynab_api import Client

logger = logging.getLogger(__name__)

TOKEN_LOST = "Your YNAB token is no longer in the keychain."

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
        self.stale = False
        """A view wrote to YNAB after the last sync started, so the store lags behind."""
        self._store: Store | None = None
        self._sync_task: asyncio.Task[SyncResult | None] | None = None

    @property
    def store(self) -> Store:
        """The local store, opened (and created) on first use."""
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

    def load(self) -> None:
        """Read the config from disk and rebuild everything that depends on it."""
        self._store = None
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

    def reload(self) -> None:
        """Pick up a config that was just saved."""
        self.load()

    async def sync(self, progress: Progress = _NO_PROGRESS) -> SyncResult | None:
        """Bring the store up to date with YNAB. Concurrent callers share the running sync.

        Returns None when the app is shutting down before YNAB answers.
        """
        if self._sync_task is None or self._sync_task.done():
            self._sync_task = asyncio.ensure_future(self._sync(progress))
        return await asyncio.shield(self._sync_task)

    def fresh(self, max_age: dt.timedelta) -> bool:
        """Whether the store can be shown as is: synced within `max_age`, nothing written since."""
        if self.stale or self.syncing or self.last_sync is None:
            return False
        return dt.datetime.now(dt.UTC) - self.last_sync <= max_age

    def invalidate(self) -> None:
        """Call after writing to YNAB: the next view that needs fresh data syncs first.

        Starts the sync right away too, so it is usually done before the user gets there.
        """
        self.stale = True
        self.sync_in_background()

    async def _sync(self, progress: Progress) -> SyncResult | None:
        config, client = self.require()
        # A write during this sync sets it again, and the next `fresh()` syncs once more
        self.stale = False
        try:
            result = await run.io_bound(self.store.sync, client, config.budget.id, progress)
        except Exception as error:
            self.sync_error = str(error)
            raise
        self.sync_error = None
        self.last_sync = self.store.last_sync(config.budget.id)
        # A sync that brought nothing is not worth a line in the feed (one runs at every start)
        if result is not None and (
            result.full or result.transactions_changed or result.ghosts_removed
        ):
            changes = result.transactions_changed
            ghosts = result.ghosts_removed
            message = f"Synced · {changes} change{'' if changes == 1 else 's'} from YNAB"
            details: dict[str, int | bool] = {"changes": changes, "full": result.full}
            if ghosts:
                message += f" · {ghosts} stale removed"
                details["ghosts"] = ghosts
            await run.io_bound(self.store.log, config.budget.id, "sync", message, details)
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

        background_tasks.create(sync_logged(), name="yul store sync")

    async def budget_accounts(self) -> list[StoredAccount]:
        """Every account of the budget, from the store once synced, from YNAB before that."""
        config, client = self.require()
        if stored := self.store.accounts(config.budget.id):
            return stored

        accounts = await run.io_bound(client.accounts, config.budget.id) or []
        return sorted(
            (
                StoredAccount(
                    id=str(account.id),
                    name=account.name,
                    type=account.type.value,
                    closed=account.closed,
                    on_budget=account.on_budget,
                    balance=account.balance,
                    cleared_balance=account.cleared_balance,
                    uncleared_balance=account.uncleared_balance,
                )
                for account in accounts
                if not account.deleted
            ),
            key=lambda account: account.name,
        )


def default_bucket(account_type: str) -> Bucket:
    """The net worth bucket of a YNAB account type given as its string value."""
    try:
        return bucket_for(AccountType(account_type))
    except ValueError:
        return Bucket.ASSETS


_STATE: AppState | None = None


def state() -> AppState:
    """The state shared by every page of this process, loaded on first use."""
    global _STATE
    if _STATE is None:
        _STATE = AppState()
        _STATE.load()
    return _STATE
