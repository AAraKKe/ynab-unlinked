"""Settings › Data & privacy: what yul keeps on this computer, the rows left out of imports,
resync, and reset everything."""

from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING

from nicegui import ui

from ynab_unlinked import keychain
from ynab_unlinked.config import LatestConfig
from ynab_unlinked.local_data import local_data_paths
from ynab_unlinked.web import shell
from ynab_unlinked.web.components import button
from ynab_unlinked.web.state import state
from ynab_unlinked.web.views.settings import left_out
from ynab_unlinked.web.views.settings.common import kv
from ynab_unlinked.web.wording import human_size, ynab_error_message

if TYPE_CHECKING:
    from ynab_unlinked.web.views.settings import Settings

SERVER_DESCRIPTION = "On this computer only. Nothing is sent anywhere but YNAB."


def token_wording() -> str:
    """Where the token is kept, in the app's words (the CLI has its own in `privacy`)."""
    if (name := keychain.backend_name()) is not None:
        return f"In your {name}, as the item “{keychain.service_name()}”. Not in any file."
    return "In the settings file, since no keychain was found on this computer."


async def render(page: Settings) -> None:
    current = state()
    current.require()
    path = current.store.path
    size = human_size(path.stat().st_size) if path.is_file() else "not created yet"
    with ui.element("div").classes("yul-kv"):
        kv("Where it runs")
        ui.label(SERVER_DESCRIPTION)
        kv("Budget copy")
        ui.label(
            f"{path} · {size} · {shell.sync_label(current.last_sync, dt.datetime.now(dt.UTC))}"
        ).classes("yul-mono").style("word-break:break-all").mark("store-info")
        kv("Settings file")
        ui.label(str(LatestConfig.path())).classes("yul-mono").style("word-break:break-all")
        kv("YNAB token")
        ui.label(token_wording()).mark("token-location")
        kv("What is kept")
        with ui.element("div").classes("yul-muted yul-small"):
            ui.label("The budget, banks, account settings and adjustment settings.")
            ui.label("A copy of the budget's transactions and accounts, and a log of what yul did.")
            ui.label("The rows of your statements you left out of imports.")
            ui.label("Nothing leaves this computer except calls to api.ynab.com.")

    await left_out.render(page)

    with ui.element("div").classes("yul-row").style("margin-top:14px;gap:8px"):
        resync = button("Resync from scratch", small=True).mark("resync")
        button("Reset all data", kind="danger", small=True, on_click=reset).mark("reset-data")

    async def resync_now() -> None:
        resync.disable()
        try:
            result = await state().resync()
        except Exception as error:
            shell.notify(f"Sync failed. {ynab_error_message(error)}", "error")
        else:
            if result is not None:
                shell.notify(shell.sync_message(result))
        finally:
            resync.enable()
        await page.rerender()

    resync.on("click", resync_now)


async def reset() -> None:
    paths = local_data_paths()
    lines = [f"Delete {path}" for path in paths]
    if (name := keychain.backend_name()) is not None:
        lines.append(f"Remove the token from your {name}")
    lines.append("Your YNAB budget is not touched. Revoke the token in YNAB if you stop using yul.")
    if not await shell.confirm("Reset all data?", lines, "Delete everything", danger=True):
        return
    await state().reset(paths)
    ui.navigate.to(shell.ONBOARDING_PATH)
