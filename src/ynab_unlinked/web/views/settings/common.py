"""What every Settings tab uses: the config to read, the key cell of a grid, the accounts."""

from __future__ import annotations

from nicegui import ui

from ynab_unlinked.config import LatestConfig
from ynab_unlinked.store import StoredAccount
from ynab_unlinked.web import shell
from ynab_unlinked.web.state import state
from ynab_unlinked.web.wording import ynab_error_message
from ynab_unlinked.web.ynab import fallback_accounts


def current_config() -> LatestConfig:
    """The config as the app holds it, for reading. Changes go through `shell.save_config`."""
    config, _ = state().require()
    return config


def kv(key: str) -> None:
    """The key cell of a `yul-kv` grid row; the value follows it."""
    ui.label(key).classes("k")


async def all_accounts() -> list[StoredAccount]:
    """Every account of the budget, closed ones included, or the configured ones when YNAB
    cannot be reached."""
    try:
        return await state().budget_accounts()
    except Exception as error:
        shell.notify(ynab_error_message(error), "warn")
        return fallback_accounts(current_config())


async def open_accounts() -> list[StoredAccount]:
    """The budget's open accounts, or the configured ones when YNAB cannot be reached."""
    return [account for account in await all_accounts() if not account.closed]
