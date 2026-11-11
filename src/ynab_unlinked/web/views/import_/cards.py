"""The cards and footers of the steps: the Files and Review footers, a card per file to
import in Review and Done, and the Done summary."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from nicegui import ui

from ynab_unlinked.core.importing import ImportResult
from ynab_unlinked.formatter import Formatter
from ynab_unlinked.web import shell
from ynab_unlinked.web.components import button, check, glass_card, pill, spinner
from ynab_unlinked.web.views.import_.data import (
    ImportFile,
    done_summary,
    held_count,
    left_out_count,
)
from ynab_unlinked.web.views.import_.tables import RowActions, badge, plan_table
from ynab_unlinked.web.wording import plural


def files_footer(
    files: Sequence[ImportFile],
    active: Sequence[ImportFile],
    ready: Sequence[ImportFile],
    on_review: Callable[[], Any],
) -> None:
    """The sticky footer of Files: what is ready, and Review once every file is settled."""
    blocked = any(item.blocking for item in files)
    transactions = sum(len(item.plan.rows) for item in ready if item.plan)
    new = sum(len(item.plan.new_rows) for item in ready if item.plan)
    held = sum(held_count(item.plan) for item in ready if item.plan)
    with ui.element("div").classes("yul-foot").mark("files-footer"):
        with ui.element("div").classes("yul-grow yul-foot-stat"):
            ui.label(plural(len(active), "file"))
            ui.label(plural(transactions, "transaction"))
            ui.label(f"{new} new").classes("yul-good")
            if held:
                ui.label(f"{held} to check").classes("yul-warn").mark("files-held")
            ui.label(f"{transactions - new - held} already in YNAB").classes("yul-muted")
            if unsupported := len(files) - len(active):
                ui.label(f"{plural(unsupported, 'file')} skipped").classes("yul-faint")
        review = button(
            f"Review {plural(len(ready), 'file')}", kind="primary", on_click=on_review
        ).mark("review")
        if blocked or not ready:
            review.disable()


def review_footer(
    ready: Sequence[ImportFile],
    *,
    reconciled: bool,
    on_reconciled: Callable[[bool], Any],
    on_back: Callable[[], Any],
    on_import: Callable[[], Any],
) -> None:
    """The sticky footer of Review: the totals, "import as reconciled", Back and Import."""
    new = sum(len(item.plan.new_rows) for item in ready if item.plan)
    left_out = sum(left_out_count(item.plan) for item in ready if item.plan)
    held = sum(held_count(item.plan) for item in ready if item.plan)
    accounts = {item.account_id for item in ready if item.plan and item.plan.new_rows}
    with ui.element("div").classes("yul-foot").mark("review-footer"):
        with ui.element("div").classes("yul-grow yul-foot-stat"):
            ui.label(
                f"{plural(new, 'new transaction')} in {plural(len(accounts), 'account')}"
            ).style("font-weight:600").mark("review-summary")
            if held:
                ui.label(f"{held} to check").classes("yul-warn").mark("review-held")
            if left_out:
                ui.label(f"{left_out} left out").classes("yul-muted").mark("review-left-out")
            switch = ui.switch("import as reconciled", value=reconciled).mark("reconciled")
            switch.on_value_change(lambda e: on_reconciled(bool(e.value)))
        button("Back", kind="ghost", on_click=on_back).mark("back")
        go = button(
            f"Import {plural(new, 'transaction')}", kind="primary", on_click=on_import
        ).mark("import")
        if not new:
            go.disable()


def review_card(
    item: ImportFile, account_name: str, formatter: Formatter, actions: RowActions
) -> None:
    """A ready file in Review: its bank, account and file, the counts and its rows."""
    assert item.plan is not None and item.candidate is not None
    with glass_card().classes("yul-imp-card").mark(f"review-{item.key}"):
        with ui.element("div").classes("yul-row").style("margin-bottom:8px"):
            badge(item.suffix, small=True)
            ui.label(item.candidate.loader.title).style("font-weight:600")
            pill(f"→ {account_name}")
            ui.label(item.name).classes("yul-faint yul-small")
            ui.element("span").classes("yul-grow")
            if held := held_count(item.plan):
                pill(f"{held} to check", "warn").mark(f"review-held-{item.key}")
            if left_out := left_out_count(item.plan):
                pill(f"{left_out} left out").mark(f"review-left-out-{item.key}")
            pill(f"{len(item.plan.new_rows)} new / {len(item.plan.rows)}", "acc").mark(
                f"review-count-{item.key}"
            )
        plan_table(item.plan, formatter, item.key, actions)


@dataclass(frozen=True)
class Progress:
    """A file's card in Done: its status line and progress bar, updated as it is committed."""

    key: int
    status: ui.element
    bar: ui.element
    fill: ui.element

    def nothing_new(self) -> None:
        self.fill.style("width:100%")

    def running(self) -> None:
        self.status.clear()
        with self.status:
            spinner()
        self.bar.classes(add="active")
        self.fill.style("width:60%")

    def failed(self, message: str) -> None:
        self.bar.classes(remove="active")
        self.fill.style("width:100%;background:var(--bad)")
        self.status.clear()
        with self.status:
            ui.label(message).classes("yul-bad").mark(f"commit-error-{self.key}")

    def created(self, result: ImportResult) -> None:
        self.bar.classes(remove="active")
        self.fill.style("width:100%")
        self.status.clear()
        with self.status:
            text = f"{result.created} created"
            if result.duplicate_import_ids:
                text += f" · {plural(len(result.duplicate_import_ids), 'duplicate')}"
            ui.label(text).classes("yul-good")


def progress_card(item: ImportFile, account_name: str) -> Progress:
    """A file's card in Done, waiting (or "nothing new") until its turn comes."""
    assert item.plan is not None
    with glass_card().classes("yul-imp-card").mark(f"progress-{item.key}"):
        with ui.element("div").classes("yul-row").style("margin-bottom:8px"):
            ui.label(account_name).style("font-weight:600")
            ui.label(f"{plural(len(item.plan.new_rows), 'transaction')} · {item.name}").classes(
                "yul-muted"
            )
            ui.element("span").classes("yul-grow")
            status = ui.element("div").classes("yul-row yul-small")
        with status:
            ui.label("waiting" if item.plan.new_rows else "nothing new").classes("yul-muted")
        with ui.element("div").classes("yul-prog") as bar:
            fill = ui.element("i").style("width:0%")
    return Progress(key=item.key, status=status, bar=bar, fill=fill)


def done_card(
    created: int,
    duplicates: int,
    skipped: int,
    failed: int,
    left_out: int,
    held: int,
    on_more: Callable[[], Any],
) -> None:
    """What the commit did, with Reconcile next and "Import more"."""
    with glass_card().classes("yul-imp-done").mark("done-card"):
        check(big=True)
        ui.label(f"{plural(created, 'transaction')} imported").classes("yul-h2").mark("done-title")
        ui.label(done_summary(duplicates, skipped, failed, left_out, held)).classes(
            "yul-lede"
        ).mark("done-summary")
        with ui.element("div").classes("yul-row").style("justify-content:center"):
            button(
                "Reconcile these accounts",
                kind="primary",
                on_click=lambda: ui.navigate.to(shell.RECONCILE_PATH),
            ).mark("reconcile")
            button("Import more", on_click=on_more).mark("import-more")
