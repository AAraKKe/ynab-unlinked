"""Settings › Data & privacy: the rows left out of imports, each with "Include again"."""

from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

from nicegui import run, ui

from ynab_unlinked.store import ExcludedRow, Store
from ynab_unlinked.web import shell
from ynab_unlinked.web.components import button, section_title
from ynab_unlinked.web.state import state
from ynab_unlinked.web.wording import left_out_entry

if TYPE_CHECKING:
    from ynab_unlinked.web.views.settings import Settings

LEDE = (
    "Rows of your bank statements you left out in an import's review. Later imports leave "
    "them out too; include one again to import it next time."
)


def read(store: Store, budget_id: str) -> tuple[list[ExcludedRow], dict[str, str]]:
    """The rows left out and the names of the budget's accounts. Blocking: run it io_bound."""
    return store.excluded(budget_id), {a.id: a.name for a in store.accounts(budget_id)}


async def load() -> tuple[list[ExcludedRow], dict[str, str]]:
    """The rows left out and their account names, read off the loop (empty when it fails)."""
    config, _ = state().require()
    try:
        return await run.io_bound(read, state().store, config.budget.id) or ([], {})
    except Exception as error:
        shell.notify(f"Could not read the rows left out of imports: {error}", "warn")
        return [], {}


def draw(page: Settings, rows: list[ExcludedRow], names: dict[str, str]) -> None:
    """The section, from what `load` read."""
    formatter = state().require_formatter()

    with ui.element("div").classes("yul-left-out").mark("left-out"):
        section_title("Rows left out of imports")
        ui.label(LEDE).classes("yul-muted yul-small")
        if not rows:
            ui.label("No rows are left out.").classes("yul-faint yul-small").style(
                "margin-top:8px"
            ).mark("left-out-empty")
            return
        with ui.element("table").classes("yul-imp-table"):
            with ui.element("tr"):
                for title, align in (
                    ("Date", ""),
                    ("Payee", ""),
                    ("Account", ""),
                    ("Amount", "r"),
                    ("", "r"),
                ):
                    with ui.element("th").classes(align):
                        ui.label(title)
            for index, row in enumerate(rows):
                account_name = names.get(row.account_id, row.account_id)
                with ui.element("tr").mark(f"left-out-{index}"):
                    with ui.element("td").classes("num"):
                        ui.label(formatter.format_date(row.date))
                    with ui.element("td"):
                        ui.label(row.payee)
                    with ui.element("td"):
                        ui.label(account_name)
                    with ui.element("td").classes("r num"):
                        ui.label(formatter.format_amount_milli(row.amount))
                    with ui.element("td").classes("r"):
                        button(
                            "Include again",
                            kind="ghost",
                            small=True,
                            on_click=partial(include_again, page, row, account_name),
                        ).mark(f"include-again-{index}")


async def include_again(page: Settings, row: ExcludedRow, account_name: str) -> None:
    config, _ = state().require()
    store = state().store
    message, details = left_out_entry("include", row, account_name, state().require_formatter())

    try:
        await run.io_bound(store.include, config.budget.id, row.account_id, row.import_id)
        await run.io_bound(store.log, config.budget.id, "include", message, details)
    except Exception as error:
        shell.notify(f"Could not save it on this computer: {error}", "error")
        return
    shell.notify(f"{row.payee} included in imports again")
    await page.rerender()
