"""After the import: removing the statement files from this computer.

The browser gave yul a copy of each file, not where it is, so the originals are looked for
by name and content (`core.imported_files`). What happens to the ones found is the setting
`imported_files`: asked in a dialog, where "Don't ask again" saves the answer, or done
without asking. A file found in more than one place is always asked about. What is removed
is noted in the activity log, each file with where it was.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass

from nicegui import run, ui

from ynab_unlinked.config import ImportedFiles, LatestConfig
from ynab_unlinked.core.imported_files import (
    REMOVE_KIND,
    Imported,
    Located,
    Original,
    locate,
    removal_log,
    remove_originals,
    shown,
)
from ynab_unlinked.web import shell
from ynab_unlinked.web.components import button, dialog_box, run_dialog
from ynab_unlinked.web.state import state
from ynab_unlinked.web.views.import_.data import (
    REMOVE_COPIES,
    REMOVE_FAILED,
    REMOVE_REMEMBER,
    REMOVE_REMEMBER_HINT,
    SETTING_HINT,
    missing_line,
    not_removed_lines,
    remove_lede,
    remove_title,
    removed_line,
)
from ynab_unlinked.web.wording import IMPORTED_FILES_SAVED, plural

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Answer:
    remove: bool
    remember: bool
    """ "Don't ask again" was ticked: the answer becomes the setting."""


async def offer_removal(files: Sequence[Imported], box: ui.element) -> None:
    """Remove the originals of `files`, asking first unless the setting says to remove them.

    `box` gets one line per outcome (what was removed, what could not be, what was not
    found). Nothing is looked for when the setting is to keep the files.
    """
    config, _ = state().require()
    mode = config.imported_files
    if mode is ImportedFiles.KEEP or not files:
        return
    try:
        located = await run.io_bound(locate, files)
    except Exception:
        logger.exception("The imported files could not be looked for")
        located = None
    if box.is_deleted:
        return
    with box:
        if located is None:
            shell.notify(REMOVE_FAILED, "warn")
            return
        if not located.originals:
            _line(missing_line(located.missing), "removal-missing")
            return
        if mode is ImportedFiles.ASK or located.copies:
            answer = await _ask(located, remember=mode is ImportedFiles.ASK)
            if answer is None or box.is_deleted:
                return
            # Said under the Done card, where it stays: the line in the top bar is replaced
            # by the next one
            if answer.remember and (saved := await _remember(answer.remove)) is not None:
                _line(f"{saved}. {SETTING_HINT}", "removal-saved")
            if not answer.remove:
                return
        removal = await run.io_bound(remove_originals, located.originals)
        if removal is None or box.is_deleted:
            return
        if removal.removed:
            _line(removed_line(removal), "removal-done")
            shell.notify(f"{plural(len(removal.removed), 'file')} removed from this computer")
            await _log(removal.removed)
        for index, line in enumerate(not_removed_lines(removal)):
            _line(line, f"removal-failed-{index}").classes(add="yul-warn")
        if removal.failed:
            shell.notify("Some imported files could not be removed", "warn")
        if located.missing:
            _line(missing_line(located.missing), "removal-missing")


async def _log(removed: Sequence[Original]) -> None:
    """Note what was removed in the activity log, so Home says which files went."""
    config, _ = state().require()
    message, details = removal_log(removed)
    try:
        await run.io_bound(state().store.log, config.budget.id, REMOVE_KIND, message, details)
    except Exception as error:
        shell.notify(f"Could not record the removal in the activity log: {error}", "warn")


def _line(text: str, marker: str) -> ui.label:
    return ui.label(text).classes("yul-muted yul-small").mark(marker)


async def _remember(remove: bool) -> str | None:
    """Save the answer as the setting. Returns what to say, None when the save failed (a
    toast said so)."""
    choice = ImportedFiles.REMOVE if remove else ImportedFiles.KEEP

    def change(config: LatestConfig) -> None:
        config.imported_files = choice

    return IMPORTED_FILES_SAVED[choice] if await shell.save_config(change) else None


async def _ask(located: Located, *, remember: bool) -> Answer | None:
    """The dialog: the files found, "Don't ask again" (with `remember`), Keep and Remove.

    None when it is dismissed: the files stay and nothing is saved.
    """
    count = len(located.originals)
    lede = remove_lede(count)
    if located.copies:
        lede = f"{lede} {REMOVE_COPIES}"
    box = dialog_box(remove_title(count), lede=lede)
    dialog = box.dialog.mark("removal-dialog")
    tick: ui.checkbox | None = None
    with box.body:
        with ui.element("ul").classes("yul-change-list yul-imp-originals"):
            for index, original in enumerate(located.originals):
                with ui.element("li"):
                    ui.label(shown(original.path)).classes("yul-mono").mark(f"removal-file-{index}")
        if located.missing:
            ui.label(missing_line(located.missing)).classes("yul-faint yul-small").mark(
                "removal-not-found"
            )
        if remember:
            tick = ui.checkbox(REMOVE_REMEMBER).props("dense").mark("removal-remember")
            ui.label(REMOVE_REMEMBER_HINT).classes("yul-faint yul-small yul-imp-remember")

    def submit(remove: bool) -> None:
        dialog.submit(Answer(remove, remember=tick is not None and bool(tick.value)))

    with box.actions:
        keep = "Keep it" if count == 1 else "Keep them"
        button(keep, kind="ghost", on_click=lambda: submit(False)).mark("removal-keep")
        button(
            f"Remove {plural(count, 'file')}",
            kind="danger-primary",
            on_click=lambda: submit(True),
        ).mark("removal-remove")
    answer = await run_dialog(dialog)
    return answer if isinstance(answer, Answer) else None
