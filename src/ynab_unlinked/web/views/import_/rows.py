"""The file rows of the Import step Files: a row per file with its detection and the body under it.

Each row shows the badge, name and size, then what detection found: the bank (or a choice
when several read it), every option of the bank as a select, the account, the count of new
rows or the problem, and the remove button. The body, opened by a click on the row, says why
the bank matched and lists the rows. Drawing only: the actions are the flow's.
"""

from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING

from nicegui import ui

from ynab_unlinked.core.detect import Candidate, Detection
from ynab_unlinked.entities.registry import LoaderOption
from ynab_unlinked.web.components import bank_logo, button, loading, pill, set_class, spinner
from ynab_unlinked.web.views.import_.data import ImportFile, Status, option_choices
from ynab_unlinked.web.views.import_.tables import badge, plan_table, transactions_table
from ynab_unlinked.web.wording import human_size

if TYPE_CHECKING:
    from ynab_unlinked.web.views.import_.view import ImportFlow


def draw_row(flow: ImportFlow, item: ImportFile) -> None:
    row = flow.rows.get(item.key)
    if row is None or row.is_deleted:
        return
    row.clear()
    set_class(row, "off", item.status is Status.UNSUPPORTED)
    with row:
        with ui.element("div").classes("yul-imp-head") as head:
            badge(item.suffix)
            with ui.element("div").classes("yul-grow"):
                ui.label(item.name).classes("yul-imp-name")
                ui.label(human_size(item.size)).classes("yul-imp-meta")
            with ui.element("div").classes("yul-imp-det") as det:
                draw_detection(flow, item)
            det.on("click", js_handler="(e) => e.stopPropagation()")
            ui.label("›").classes("yul-imp-arrow")
        head.on("click", lambda: flow.toggle(item))
        with ui.element("div").classes("yul-imp-body"):
            draw_body(flow, item)


def draw_detection(flow: ImportFlow, item: ImportFile) -> None:
    match item.status:
        case Status.DETECTING:
            loading("Detecting…")
            return
        case Status.UNSUPPORTED:
            ui.label(item.problem or "Not supported").classes("yul-imp-reason").mark(
                f"problem-{item.key}"
            )
            remove_button(flow, item)
            return
        case _:
            pass

    detection = item.detection
    if detection is not None and detection.ambiguous:
        draw_choice(flow, item, detection)
    candidate = item.candidate
    if candidate is None:
        remove_button(flow, item)
        return

    if detection is None or not detection.ambiguous:
        bank_logo(candidate.loader.key, candidate.loader.title, size=26)
        pill(f"{candidate.loader.title} · {candidate.confidence:.0%}", "ok").mark(
            f"loader-{item.key}"
        )
    # Every option of the bank, starting from the saved defaults, changeable per file
    for option in candidate.loader.options:
        option_select(flow, item, candidate, option)
    draw_account(flow, item)

    match item.status:
        case Status.PLANNING:
            spinner()
        case Status.READY if item.plan is not None:
            total = len(item.plan.rows)
            pill(f"{len(item.plan.new_rows)} new / {total}", "acc").mark(f"count-{item.key}")
        case Status.ERROR:
            error = ui.label(item.problem or "Error").classes("yul-imp-reason yul-bad")
            error.mark(f"error-{item.key}")
            if candidate.transactions is not None:
                button("Retry", small=True, on_click=lambda: flow.advance(item)).mark(
                    f"retry-{item.key}"
                )
        case _:
            pass
    remove_button(flow, item)


def draw_choice(flow: ImportFlow, item: ImportFile, detection: Detection) -> None:
    if item.candidate is None:
        ui.label("Which bank?").classes("yul-faint yul-small")
    with ui.element("div").classes("yul-imp-seg").mark(f"choice-{item.key}"):
        for candidate in detection.candidates:
            if candidate.transactions is None:
                continue
            count = len(candidate.transactions)
            option = ui.label(f"{candidate.loader.title} · {count}").classes("opt")
            option.mark(f"choose-{item.key}-{candidate.loader.key}")
            if item.candidate is not None and item.candidate.loader == candidate.loader:
                option.classes(add="on")
            option.on("click", lambda _, c=candidate: flow.use(item, c))


def option_select(
    flow: ImportFlow, item: ImportFile, candidate: Candidate, option: LoaderOption
) -> None:
    current = candidate.options.get(option.key, "")
    select = ui.select(
        option_choices(option, current, dt.date.today()), value=current or None
    ).props("outlined dense options-dense")
    select.props["title"] = option.label
    select.mark(f"option-{item.key}-{option.key}")
    select.on_value_change(lambda e, key=option.key: flow.change_option(item, key, str(e.value)))


def draw_account(flow: ImportFlow, item: ImportFile) -> None:
    if item.account_id is not None and not item.account_chosen:
        pill(f"→ {flow.account_name(item.account_id)}").mark(f"account-{item.key}")
        return
    select = ui.select(flow.account_names or {}, value=item.account_id, label="Account").props(
        "outlined dense options-dense"
    )
    select.style("min-width:170px").mark(f"account-select-{item.key}")
    select.on_value_change(lambda e: flow.pick_account(item, e.value))


def remove_button(flow: ImportFlow, item: ImportFile) -> None:
    remove = button(icon_name="x", kind="ghost", small=True, on_click=lambda: flow.remove(item))
    remove.props["title"] = "Remove"
    remove.mark(f"remove-{item.key}")


def draw_body(flow: ImportFlow, item: ImportFile) -> None:
    if item.status is Status.UNSUPPORTED:
        ui.label(item.problem or "Not a statement yul can read.").classes("yul-imp-note")
        return
    candidate = item.candidate
    if item.status is Status.ERROR and item.problem:
        ui.label(item.problem).classes("yul-imp-note yul-bad")
    if candidate is None:
        if item.status is Status.CHOOSE:
            ui.label("More than one bank reads this file. Pick the one that exported it.")
        return
    ui.label(f"Matched because: {candidate.reason}.").classes("yul-imp-note")
    if item.plan is not None:
        plan_table(item.plan, flow.formatter(), item.key)
    elif candidate.transactions is not None:
        transactions_table(candidate.transactions, flow.formatter())
