"""Activity log entries for what the CLI wrote to YNAB, so `yul app` shows it too.

The entries go to the local store with the shapes the app writes (ARCHITECTURE 3.4): Home
reads the newest `import` per bank and the newest `reconcile`. The next sync of the app
brings the transactions themselves. A store that cannot be opened never fails the command.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any

from ynab_unlinked import display
from ynab_unlinked.config import LatestConfig
from ynab_unlinked.store import Store, store_path

logger = logging.getLogger(__name__)


def _plural(count: int, noun: str) -> str:
    return f"{count} {noun}{'' if count == 1 else 's'}"


def _open_store() -> Store | None:
    try:
        return Store(store_path())
    except Exception as error:
        display.warning(f"YNAB is updated, but yul could not note it in its activity log: {error}")
        return None


def _write(store: Store, budget_id: str, kind: str, message: str, details: dict[str, Any]) -> None:
    try:
        store.log(budget_id, kind, message, details)
    except Exception as error:
        display.warning(f"YNAB is updated, but yul could not note it in its activity log: {error}")


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
) -> None:
    """One `import` entry; `loader` is the config key of the bank (`Entity.name()`)."""
    if (store := _open_store()) is None:
        return
    account_name = _account_name(store, config, account_id)
    _write(
        store,
        config.budget.id,
        "import",
        f"Imported {_plural(created, 'transaction')} to {account_name} from {file}",
        {
            "loader": loader,
            "account_id": account_id,
            "account_name": account_name,
            "file": file,
            "created": created,
            "duplicates": duplicates,
            "skipped": skipped,
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
        f"Reconciled {_plural(count, 'transaction')} in {_plural(len(accounts), 'account')}",
        {
            "count": count,
            "accounts": [
                {"id": account_id, "name": name, "count": locked}
                for account_id, name, locked in accounts
            ],
        },
    )
