"""The command palette: one box to reach every page, tab, category, account and action.

Opened from the top bar's search button or with ⌘K / Ctrl+K (`theme.KEYS_JS` sends the
`yul-palette` event). The commands and the matching are `web.palette`'s; this module draws
them. One per browser tab, created by the shell.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable, Mapping
from typing import Any

from nicegui import run, ui

from ynab_unlinked.web import palette
from ynab_unlinked.web.components import clickable, icon, set_class
from ynab_unlinked.web.state import state

PLACEHOLDER = "Search pages, settings, categories and accounts"
NO_RESULTS = "Nothing matches. Try a page, a category or an account."


class PaletteDialog:
    def __init__(
        self,
        static: Callable[[], list[palette.Command]],
        actions: Mapping[str, Callable[[], Any]],
    ) -> None:
        self.static = static
        """The commands known without reading the budget: pages, tabs and actions."""
        self.actions = actions
        self.commands: list[palette.Command] = []
        self.results: list[palette.Command] = []
        self.rows: list[ui.element] = []
        self.active = 0
        with (
            ui.dialog().props("position=top no-shake") as self.dialog,
            ui.element("div").classes("yul-palette").mark("palette"),
        ):
            with ui.element("div").classes("yul-palette-head"):
                icon("search", 18)
                self.input = (
                    ui.input(placeholder=PLACEHOLDER, on_change=lambda e: self._show(e.value))
                    .props("borderless dense autofocus")
                    .classes("yul-palette-input")
                    .mark("palette-input")
                )
                ui.label("esc").classes("yul-kbd")
            self.list = ui.element("div").classes("yul-palette-list").mark("palette-results")
            with ui.element("div").classes("yul-palette-foot"):
                ui.label("↑↓").classes("yul-kbd")
                ui.label("to move")
                ui.label("↵").classes("yul-kbd")
                ui.label("to open")
        self.input.on("keydown.down.prevent", lambda: self._move(1))
        self.input.on("keydown.up.prevent", lambda: self._move(-1))
        self.input.on("keydown.enter.prevent", self._run_active)

    async def open(self) -> None:
        """Show it with the pages and actions, then add the budget's categories and accounts."""
        if self.dialog.value:
            return
        self.commands = self.static()
        self.input.value = ""
        self._show("")
        self.dialog.open()
        current = state()
        if not current.configured:
            return
        config, _ = current.require()
        extra = await run.io_bound(palette.budget_commands, current.store, config)
        if extra is None or self.dialog.is_deleted:  # the app is shutting down, or the tab left
            return
        self.commands = [*self.static(), *extra]
        if self.input.value:
            self._show(self.input.value)

    def _show(self, query: str | None) -> None:
        self.results = palette.search(self.commands, query or "")
        self.active = 0
        self.rows = []
        self.list.clear()
        with self.list:
            if not self.results:
                ui.label(NO_RESULTS).classes("yul-palette-none").mark("palette-none")
                return
            section: str | None = None
            for index, command in enumerate(self.results):
                if command.section != section:
                    section = command.section
                    ui.label(section).classes("yul-palette-section")
                self.rows.append(self._row(index, command))

    def _row(self, index: int, command: palette.Command) -> ui.element:
        with ui.element("div").classes("yul-palette-row").mark(f"palette-{command.key}") as row:
            icon(command.icon, 18)
            ui.label(command.title).classes("yul-palette-title")
            if command.hint:
                ui.label(command.hint).classes("yul-palette-hint")
        if index == self.active:
            row.classes(add="on")
        clickable(row, lambda: self._run(command), role="option")
        return row

    def _move(self, step: int) -> None:
        if not self.rows:
            return
        self.active = (self.active + step) % len(self.rows)
        for index, row in enumerate(self.rows):
            set_class(row, "on", index == self.active)
        ui.run_javascript(
            f"getHtmlElement({self.rows[self.active].id})?.scrollIntoView({{block: 'nearest'}})"
        )

    async def _run_active(self) -> None:
        if self.results:
            await self._run(self.results[self.active])

    async def _run(self, command: palette.Command) -> None:
        self.dialog.close()
        if command.path is not None:
            ui.navigate.to(command.path)
        elif command.action is not None and (action := self.actions.get(command.action)):
            result = action()
            if inspect.isawaitable(result):
                await result
