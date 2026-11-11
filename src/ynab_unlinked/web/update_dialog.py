"""The sidebar's "Update" button and the dialog that updates yul and restarts it."""

from __future__ import annotations

import asyncio
import logging

from nicegui import run, ui

from ynab_unlinked.__about__ import __version__
from ynab_unlinked.core.update import CHANGELOG_URL, Install, UpdateError, Upgrade, upgrade_plan
from ynab_unlinked.web.components import DialogBox, button, dialog_box, icon, loading, run_dialog
from ynab_unlinked.web.update import updates

logger = logging.getLogger(__name__)

LOOK_SECONDS = 5.0
"""How often a tab looks for a newer yul found meanwhile, and whether a check is due."""
LAST_WORDS_SECONDS = 0.6
"""How long the dialog's last line gets to reach the browser before the server stops."""

CONFIRM = (
    "The new version will be downloaded and this page refreshed once any ongoing operation is done."
)
BY_HAND = "This yul cannot update itself. Run this in a terminal, then start yul again:"
FROM_SOURCE = (
    "This yul runs from its source code, so it cannot update itself. Update it where you "
    "got it, then start yul again."
)
UPDATING = "Updating yul…"
KEEP_OPEN = "Keep this page open."
FAILED = f"The update did not work. yul {__version__} keeps running."
RETRY_BY_HAND = "You can run it yourself in a terminal, then start yul again:"


def out_line(version: str) -> str:
    return f"yul {version} is out"


def update_button() -> ui.element:
    """The sidebar's button, shown once a newer yul is known. A click opens the dialog.

    Each tab looks right away and every few seconds after: it runs the check when one is
    due, and shows what it or another tab found.
    """
    with ui.element("button").classes("yul-update").mark("update") as element:
        icon("upload", 14)
        ui.label("Update").classes("yul-update-label")
    element.props["type"] = "button"
    element.on("click", update_dialog)

    async def look() -> None:
        status = updates()
        if status.due():
            await status.check()
        if element.is_deleted:
            return
        version = status.available
        element.set_visibility(version is not None)
        if version is not None:
            element.props["title"] = out_line(version)
            element.props["aria-label"] = f"Update to yul {version}"
            element.update()

    element.set_visibility(updates().available is not None)
    ui.timer(0, look, once=True)
    ui.timer(LOOK_SECONDS, look)
    return element


def _command(upgrade: Upgrade) -> None:
    if upgrade.shown is not None:
        ui.label(upgrade.shown).classes("yul-update-cmd").mark("update-command")


def _close(box: DialogBox) -> None:
    box.actions.clear()
    with box.actions:
        button("Close", on_click=lambda: box.dialog.submit(None)).mark("update-close")


async def _run(box: DialogBox, upgrade: Upgrade) -> None:
    """Update, then restart. On a failure the dialog says why and how to do it by hand."""
    status = updates()
    box.dialog.props("persistent")
    box.actions.clear()
    box.body.clear()
    with box.body, ui.element("div").classes("yul-row").mark("update-running"):
        loading(UPDATING)
        ui.label(KEEP_OPEN).classes("yul-faint yul-small")
    try:
        installed = await status.update(upgrade)
    except Exception as error:
        # Whatever went wrong, the dialog must not stay on "Updating…" with no way out
        if not isinstance(error, UpdateError):
            logger.exception("The update failed unexpectedly")
        if box.dialog.is_deleted:
            return
        box.dialog.props(remove="persistent")
        box.body.clear()
        with box.body:
            ui.label(FAILED).classes("yul-bad").mark("update-failed")
            ui.label(str(error)).classes("yul-update-cmd yul-update-out").mark("update-output")
            ui.label(RETRY_BY_HAND).classes("yul-muted")
            _command(upgrade)
        _close(box)
        return
    if not box.dialog.is_deleted:
        box.body.clear()
        with box.body, ui.element("div").classes("yul-row").mark("update-done"):
            loading(f"yul {installed} is installed. Starting it again…")
    # The line above must reach the browser: the server is gone right after
    await asyncio.sleep(LAST_WORDS_SECONDS)
    status.restart()


async def update_dialog() -> None:
    """Offer the update: one line and one primary action, or how to do it by hand.

    The confirmation does not say how yul updates itself; the command only shows where the
    user has to run it (an install yul cannot update, a failed update).
    """
    status = updates()
    version = status.available
    if version is None or status.updating:
        return
    upgrade = await run.io_bound(upgrade_plan, web=True)

    box = dialog_box(f"Update to yul {version}")
    box.card.mark("update-dialog")
    with box.body:
        if upgrade.automatic:
            ui.label(CONFIRM).classes("yul-lede").mark("update-confirm")
        else:
            ui.label(FROM_SOURCE if upgrade.install is Install.SOURCE else BY_HAND).classes(
                "yul-lede"
            ).mark("update-by-hand")
            _command(upgrade)
        ui.link("See what changed", CHANGELOG_URL, new_tab=True).classes(
            "yul-link yul-small yul-update-link"
        ).mark("update-changes")
    if upgrade.automatic:
        with box.actions:
            button("Cancel", kind="ghost", on_click=lambda: box.dialog.submit(None)).mark(
                "update-cancel"
            )
            button("Update and restart", kind="primary", on_click=lambda: _run(box, upgrade)).mark(
                "update-run"
            )
    else:
        _close(box)
    await run_dialog(box.dialog)
