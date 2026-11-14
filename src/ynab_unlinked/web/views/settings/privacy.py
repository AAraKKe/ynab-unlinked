"""Settings › Data & privacy: what yul keeps on this computer, whether it looks for new
versions, the rows left out of imports, resync, and reset everything."""

from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING

from nicegui import ui

from ynab_unlinked import keychain
from ynab_unlinked.__about__ import __version__
from ynab_unlinked.config import LatestConfig
from ynab_unlinked.local_data import local_data_paths
from ynab_unlinked.web import shell
from ynab_unlinked.web.components import button
from ynab_unlinked.web.components.controls import switch
from ynab_unlinked.web.state import state
from ynab_unlinked.web.update import Updates, updates
from ynab_unlinked.web.update_dialog import out_line, update_dialog
from ynab_unlinked.web.views.settings import left_out
from ynab_unlinked.web.views.settings.common import current_config, kv
from ynab_unlinked.web.wording import human_size, ynab_error_message

if TYPE_CHECKING:
    from ynab_unlinked.web.views.settings import Settings

SERVER_DESCRIPTION = "On this computer only. Your budget is sent nowhere but YNAB."
LOOK_FOR_UPDATES = "Look for new versions"
UPDATES_HINT = (
    "Every half hour while it is open, yul asks pypi.org, where it is published, for its "
    "latest version. Nothing about you or your budget is sent."
)
LOOKING = "yul looks for new versions"
NOT_LOOKING = "yul no longer looks for new versions"
UNREACHABLE = "pypi.org could not be reached."


def token_wording() -> str:
    """Where the token is kept, in the app's words (the CLI has its own in `privacy`)."""
    if (name := keychain.backend_name()) is not None:
        return f"In your {name}, as the item “{keychain.service_name()}”. Not in any file."
    return "In the settings file, since no keychain was found on this computer."


def update_line(status: Updates) -> str:
    """What is known about a newer yul, for the line next to "Check now"."""
    if (version := status.available) is not None:
        return f"{out_line(version)}. You have {__version__}."
    if status.failed:
        return UNREACHABLE
    if status.latest is None:
        return f"You have yul {__version__}."
    return f"yul {__version__} is the latest version."


def _updates(page: Settings) -> None:
    """The switch of the daily look for a newer yul, what it found, and a look right now."""
    status = updates()

    async def save(on: bool) -> None:
        def change(config: LatestConfig) -> None:
            config.check_for_updates = on

        if not await shell.save_config(change, LOOKING if on else NOT_LOOKING):
            await page.rerender()

    async def check_now() -> None:
        check.disable()
        await status.check()
        await page.rerender()

    with ui.element("div").classes("yul-updates"):
        switch(LOOK_FOR_UPDATES, current_config().check_for_updates, save).mark("check-updates")
        ui.label(UPDATES_HINT).classes("yul-muted yul-small")
        with ui.element("div").classes("yul-row"):
            ui.label(update_line(status)).mark("update-status")
            check = button("Check now", small=True, on_click=check_now).mark("check-now")
            if status.available is not None:
                button("Update", small=True, icon_name="upload", on_click=update_dialog).mark(
                    "settings-update"
                )


async def render(page: Settings) -> None:
    current = state()
    current.require()
    # Read first: a tab drawn around an await shows half of itself for a while
    rows, names = await left_out.load()
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
        kv("Updates")
        _updates(page)
        kv("What is kept")
        with ui.element("div").classes("yul-muted yul-small"):
            ui.label("The budget, banks, account settings and adjustment settings.")
            ui.label(
                "A copy of the budget's transactions, accounts, categories and month notes, and "
                "a log of what yul did."
            )
            ui.label("The rows of your statements you left out of imports.")
            ui.label(
                "Nothing leaves this computer except calls to api.ynab.com and, while yul "
                "looks for new versions, the question to pypi.org."
            )

    left_out.draw(page, rows, names)

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
