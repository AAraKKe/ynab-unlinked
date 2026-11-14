"""The tables of the Import view: a file's rows with their status and its file badge."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Final

from nicegui import ui

from ynab_unlinked.core.importing import ImportPlan, ImportRow, RowStatus
from ynab_unlinked.formatter import Formatter
from ynab_unlinked.models import Transaction
from ynab_unlinked.web.components import PillKind, amount, button, pill, set_class
from ynab_unlinked.web.views.import_.data import (
    STATUS_LABELS,
    STATUS_MEANINGS,
    file_color,
    hidden_note,
    listed_rows,
    statuses_shown,
    twin_note,
)

_PILL_KINDS: Final[dict[RowStatus, PillKind]] = {
    RowStatus.NEW: "ok",
    RowStatus.MAYBE_IN_YNAB: "warn",
}
"""The colour of a status tag; the ones that need nothing from the user stay grey."""


def badge(suffix: str, *, small: bool = False) -> None:
    """The coloured tile with the file type ("XLSX"); `small` on the Review cards."""
    badge = ui.label((suffix or "?").upper()[:4]).classes("yul-imp-badge")
    badge.style(f"background:{file_color(suffix)}")
    if small:
        badge.classes(add="small")


@dataclass(frozen=True)
class RowActions:
    """What the Review step does when a row is left out, included or sent although it may be
    in YNAB; the Files step has none."""

    leave_out: Callable[[ImportRow], Awaitable[None]]
    include: Callable[[ImportRow], Awaitable[None]]
    send_anyway: Callable[[ImportRow], Awaitable[None]]


def status_legend(plans: Sequence[ImportPlan], hide_settled: bool = False) -> None:
    """What each tag of the rows of `plans` means, only the ones the tables list."""
    if not (statuses := statuses_shown(plans, hide_settled)):
        return
    with ui.element("div").classes("yul-imp-legend").mark("status-legend"):
        for status in statuses:
            _status(status)
            ui.label(STATUS_MEANINGS[status]).mark(f"legend-{status.value}")


def plan_table(
    plan: ImportPlan,
    formatter: Formatter,
    key: int,
    actions: RowActions | None = None,
    *,
    hide_settled: bool = False,
) -> None:
    """The rows of the file `key` with their status; with `actions`, the control to change it.

    Every row is tagged (`status_legend` says what the tags mean): rows already in YNAB (by
    import id or through a match) are dimmed, rows left out crossed out, and a row that may
    be in YNAB names the transaction there it looks like. With `hide_settled` those dimmed
    and crossed out rows are not listed, and a line under the table counts them.
    """
    rows = listed_rows(plan, hide_settled)
    if rows or not hide_settled:
        _rows(rows, formatter, key, actions)
    if hide_settled and (note := hidden_note(plan)) is not None:
        ui.label(note).classes("yul-imp-hidden").mark(f"hidden-{key}")


def _rows(
    rows: Sequence[tuple[int, ImportRow]],
    formatter: Formatter,
    key: int,
    actions: RowActions | None,
) -> None:
    with ui.element("table").classes("yul-imp-table"):
        _header(actions is not None)
        for index, row in rows:
            status = row.status
            with ui.element("tr") as tr:
                note = None
                if status is RowStatus.MAYBE_IN_YNAB and row.twin is not None:
                    note = (twin_note(row.twin, formatter), f"row-twin-{key}-{index}")
                _cells(row.transaction, formatter, note).mark(f"row-amount-{key}-{index}")
                with ui.element("td").classes("r c-status"):
                    _status(status).mark(f"row-status-{key}-{index}")
                if actions is not None:
                    with ui.element("td").classes("r c-act"):
                        _action(actions, row, status, f"{key}-{index}")
            set_class(tr, "dim", row.already_imported)
            set_class(tr, "out", status is RowStatus.EXCLUDED)


def _status(status: RowStatus) -> ui.label:
    return pill(STATUS_LABELS[status], _PILL_KINDS.get(status, "default"))


def _action(actions: RowActions, row: ImportRow, status: RowStatus, marker: str) -> None:
    match status:
        case RowStatus.NEW:
            button(
                "Leave out", kind="ghost", small=True, on_click=lambda: actions.leave_out(row)
            ).mark(f"leave-out-{marker}")
        case RowStatus.MAYBE_IN_YNAB:
            with ui.element("div").classes("yul-imp-acts"):
                button(
                    "Import anyway",
                    kind="ghost",
                    small=True,
                    on_click=lambda: actions.send_anyway(row),
                ).mark(f"import-anyway-{marker}")
                button(
                    "Leave out", kind="ghost", small=True, on_click=lambda: actions.leave_out(row)
                ).mark(f"leave-out-{marker}")
        case RowStatus.EXCLUDED:
            button(
                "Include again", kind="ghost", small=True, on_click=lambda: actions.include(row)
            ).mark(f"include-{marker}")
        case RowStatus.IN_YNAB | RowStatus.MATCHED:
            pass


def transactions_table(transactions: Sequence[Transaction], formatter: Formatter) -> None:
    """The rows a file was read into, before YNAB was asked which are new."""
    with ui.element("table").classes("yul-imp-table"):
        _header()
        for transaction in transactions:
            with ui.element("tr"):
                _cells(transaction, formatter)
                with ui.element("td").classes("r c-status"):
                    ui.label("…").classes("yul-faint")


def _header(actions: bool = False) -> None:
    with ui.element("tr").classes("head"):
        for title, align in (("Date", ""), ("Payee", ""), ("Amount", "r"), ("Status", "r")):
            with ui.element("th").classes(align):
                ui.label(title)
        if actions:
            ui.element("th")


def _cells(
    transaction: Transaction, formatter: Formatter, note: tuple[str, str] | None = None
) -> ui.label:
    """The date, payee and amount (returned); `note` is a line under the payee and its marker.

    Each cell names its column (`c-date`, `c-payee`, ...): on a phone a row is laid out as
    two lines by those names instead of as columns.
    """
    with ui.element("td").classes("num c-date"):
        ui.label(formatter.format_date(transaction.date))
    with ui.element("td").classes("c-payee"):
        ui.label(transaction.payee)
        if note is not None:
            text, marker = note
            ui.label(text).classes("yul-imp-twin").mark(marker)
    with ui.element("td").classes("r num c-amt"):
        return amount(transaction.amount, formatter)
