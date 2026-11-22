"""Done: the rows YNAB did not take, and "Don't import again" for each and for all.

YNAB refuses for good the import id of a transaction it imported once, deleted ones too
(`ImportResult.refused`). yul reads only live transactions, so such a row is offered as new
on every import and refused every time. The card says so and lets the user leave the rows
out of later imports, the same registry as "Leave out" in Review (`Store.exclude`), with an
undo in place. Nothing is written to YNAB.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from typing import Literal

from nicegui import ui

from ynab_unlinked.core.importing import ImportRow
from ynab_unlinked.formatter import Formatter
from ynab_unlinked.store import ExcludedRow
from ynab_unlinked.web import shell
from ynab_unlinked.web.components import button, glass_card, icon, pill, set_class
from ynab_unlinked.web.views.import_.data import excluded_row, refused_lede, refused_title
from ynab_unlinked.web.views.import_.tables import row_cells
from ynab_unlinked.web.wording import plural

Save = Callable[[Literal["exclude", "include"], ExcludedRow], Awaitable[bool]]
"""Saves "left out" (or "included again") on this computer and logs it; False on failure."""


@dataclass(eq=False)
class RefusedFile:
    """The rows of one committed file YNAB did not take."""

    key: int
    bank: str
    account_id: str
    account_name: str
    file: str
    rows: tuple[ImportRow, ...]
    marked: set[str] = field(default_factory=set)
    """Import ids left out of later imports from this card."""


class RefusedCard:
    """The warning under the Done card, redrawn in place after each choice."""

    def __init__(self, files: Sequence[RefusedFile], formatter: Formatter, save: Save) -> None:
        self.files = list(files)
        self.formatter = formatter
        self.save = save
        self.busy = False
        self.root = ui.element("div")
        self.draw()

    @property
    def count(self) -> int:
        return sum(len(item.rows) for item in self.files)

    @property
    def unmarked(self) -> list[tuple[RefusedFile, ImportRow]]:
        return [
            (item, row)
            for item in self.files
            for row in item.rows
            if row.import_id not in item.marked
        ]

    def draw(self) -> None:
        self.root.clear()
        with self.root, glass_card().classes("yul-imp-refused").mark("refused"):
            with ui.element("div").classes("yul-imp-refused-head"):
                icon("alert")
                ui.label(refused_title(self.count)).classes("yul-imp-refused-title").mark(
                    "refused-title"
                )
            ui.label(refused_lede(self.count)).classes("yul-imp-refused-why").mark("refused-why")
            for item in self.files:
                self.draw_file(item)
            with ui.element("div").classes("yul-imp-refused-foot"):
                if pending := len(self.unmarked):
                    if self.count > 1:
                        button(
                            "Don't import any of them again"
                            if pending == self.count
                            else "Don't import the other one again"
                            if pending == 1
                            else f"Don't import the other {pending} again",
                            on_click=self.mark_all,
                        ).mark("never-all")
                else:
                    ui.label(
                        "Later imports list "
                        + ("it" if self.count == 1 else "them")
                        + " as left out, with Include again to bring "
                        + ("it" if self.count == 1 else "one")
                        + " back."
                    ).classes("yul-muted yul-small").mark("never-all-done")

    def draw_file(self, item: RefusedFile) -> None:
        with ui.element("div").classes("yul-imp-refused-file").mark(f"refused-file-{item.key}"):
            with ui.element("div").classes("yul-imp-card-main"):
                ui.label(item.bank).classes("yul-imp-card-title")
                pill(f"→ {item.account_name}")
                ui.label(item.file).classes("yul-imp-card-file yul-faint yul-small")
            with ui.element("table").classes("yul-imp-table"):
                for index, row in enumerate(item.rows):
                    marker = f"{item.key}-{index}"
                    done = row.import_id in item.marked
                    with ui.element("tr") as tr:
                        row_cells(row.transaction, self.formatter).mark(f"refused-amount-{marker}")
                        with ui.element("td").classes("r c-act"):
                            self.draw_action(item, row, marker, done)
                    set_class(tr, "out", done)

    def draw_action(self, item: RefusedFile, row: ImportRow, marker: str, done: bool) -> None:
        if not done:
            button(
                "Don't import again",
                kind="ghost",
                small=True,
                on_click=lambda: self.mark(item, row),
            ).mark(f"never-{marker}")
            return
        with ui.element("div").classes("yul-imp-acts"):
            ui.label("Will not be imported again").classes("yul-muted yul-small").mark(
                f"never-done-{marker}"
            )
            button("Undo", kind="ghost", small=True, on_click=lambda: self.undo(item, row)).mark(
                f"undo-never-{marker}"
            )

    async def mark(self, item: RefusedFile, row: ImportRow) -> None:
        if self.busy:
            return
        self.busy = True
        try:
            if not await self.save("exclude", excluded_row(item.account_id, row)):
                return
            item.marked.add(row.import_id)
        finally:
            self.busy = False
        self.draw()
        shell.notify(f"{row.transaction.payee} will not be imported again")

    async def undo(self, item: RefusedFile, row: ImportRow) -> None:
        if self.busy:
            return
        self.busy = True
        try:
            if not await self.save("include", excluded_row(item.account_id, row)):
                return
            item.marked.discard(row.import_id)
        finally:
            self.busy = False
        self.draw()
        shell.notify(f"{row.transaction.payee} will be offered again on the next import")

    async def mark_all(self) -> None:
        if self.busy:
            return
        self.busy = True
        marked = 0
        try:
            for item, row in self.unmarked:
                if not await self.save("exclude", excluded_row(item.account_id, row)):
                    break
                item.marked.add(row.import_id)
                marked += 1
        finally:
            self.busy = False
        self.draw()
        if marked:
            shell.notify(f"{plural(marked, 'row')} will not be imported again")
