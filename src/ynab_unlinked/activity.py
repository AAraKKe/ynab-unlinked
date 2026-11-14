"""Activity log entries for what the CLI did, so `yul app` shows it too.

The entries go to the local store with the shapes the app writes (ARCHITECTURE 3.4): Home
reads the newest `import` per bank and the newest `reconcile`, and lists the files a
`remove` deleted. The next sync of the app brings the transactions themselves. A store that
cannot be opened never fails the command.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any

from ynab_unlinked.cli import display
from ynab_unlinked.config import LatestConfig
from ynab_unlinked.core.imported_files import REMOVE_KIND, Original, removal_log
from ynab_unlinked.store import Store, store_path
from ynab_unlinked.text import import_message, plural

logger = logging.getLogger(__name__)


YNAB_UPDATED = "YNAB is updated"
FILES_REMOVED = "The files are removed"


def _open_store(done: str = YNAB_UPDATED) -> Store | None:
    """The store to log in; `done` is what already happened, said when it cannot be opened."""
    try:
        return Store(store_path())
    except Exception as error:
        display.warning(f"{done}, but yul could not note it in its activity log: {error}")
        return None


def _write(
    store: Store,
    budget_id: str,
    kind: str,
    message: str,
    details: dict[str, Any],
    done: str = YNAB_UPDATED,
) -> None:
    try:
        store.log(budget_id, kind, message, details)
    except Exception as error:
        display.warning(f"{done}, but yul could not note it in its activity log: {error}")


def _account_name(store: Store, config: LatestConfig, account_id: str) -> str:
    try:
        stored = {account.id: account.name for account in store.accounts(config.budget.id)}
    except Exception as error:
        logger.warning("The accounts could not be read from the store: %s", error)
        stored = {}
    if name := stored.get(account_id):
        return name
    tracked = config.account(account_id)
    return tracked.name if tracked is not None else account_id


def log_import(
    config: LatestConfig,
    *,
    loader: str,
    account_id: str,
    file: str,
    created: int,
    duplicates: int,
    skipped: int,
    matched: int,
    excluded: int,
    held: int = 0,
) -> None:
    """One `import` entry; `loader` is the config key of the bank (`Entity.name()`).

    `matched` counts the rows of `skipped` YNAB holds through a match only, `excluded` the
    rows the user left out of imports, `held` the ones not sent because they may be in YNAB.
    """
    if (store := _open_store()) is None:
        return
    account_name = _account_name(store, config, account_id)
    _write(
        store,
        config.budget.id,
        "import",
        import_message(created, account_name, file, excluded),
        {
            "loader": loader,
            "account_id": account_id,
            "account_name": account_name,
            "file": file,
            "created": created,
            "duplicates": duplicates,
            "skipped": skipped,
            "matched": matched,
            "excluded": excluded,
            "held": held,
        },
    )


def log_reconcile(config: LatestConfig, accounts: Sequence[tuple[str, str, int]]) -> None:
    """One `reconcile` entry; `accounts` holds (id, name, transactions locked) per account."""
    if not accounts or (store := _open_store()) is None:
        return
    count = sum(locked for _, _, locked in accounts)
    _write(
        store,
        config.budget.id,
        "reconcile",
        f"Reconciled {plural(count, 'transaction')} in {plural(len(accounts), 'account')}",
        {
            "count": count,
            "accounts": [
                {"id": account_id, "name": name, "count": locked}
                for account_id, name, locked in accounts
            ],
        },
    )


def log_removal(config: LatestConfig, removed: Sequence[Original]) -> None:
    """One `remove` entry naming the statement files deleted after an import."""
    if not removed or (store := _open_store(FILES_REMOVED)) is None:
        return
    message, details = removal_log(removed)
    _write(store, config.budget.id, REMOVE_KIND, message, details, FILES_REMOVED)
