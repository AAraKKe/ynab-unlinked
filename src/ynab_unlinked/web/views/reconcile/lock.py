"""Reconcile's one write: lock the selected rows in YNAB, log it and move the checkpoint.

Moved out of `view` so the page stays readable; `ReconcileView.lock` calls `lock` here.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

from nicegui import run

from ynab_unlinked.config import LatestConfig
from ynab_unlinked.core.reconcile import reconcile
from ynab_unlinked.web import shell
from ynab_unlinked.web.state import state
from ynab_unlinked.web.views.reconcile import footer
from ynab_unlinked.web.views.reconcile.data import (
    LOCK_TIMED_OUT,
    lock_checkpoint,
    lock_confirmation,
    lock_log,
)
from ynab_unlinked.web.views.reconcile.groups import AccountGroup
from ynab_unlinked.web.wording import plural, ynab_error_message
from ynab_unlinked.ynab_api.errors import Failure, classify

if TYPE_CHECKING:
    from ynab_unlinked.web.views.reconcile.view import ReconcileView


async def lock(view: ReconcileView, groups: Sequence[AccountGroup]) -> None:
    """Lock the rows selected in `groups`, behind one confirmation (ARCHITECTURE 3.5)."""
    if view.busy:
        return
    batches = [(group, rows) for group in groups if (rows := group.to_lock())]
    if not batches:
        return
    count = sum(len(rows) for _, rows in batches)
    locked = [(group.account, [row.transaction for row in rows]) for group, rows in batches]
    if not await shell.confirm(*lock_confirmation(locked)):
        return

    view.busy = True
    view.refresh()
    if view.footer is not None:
        view.footer.clear()
        with view.footer:
            footer.locking(count)
    rows_to_lock = [row.transaction for _, rows in batches for row in rows]
    try:
        config, client = state().require()
        await run.io_bound(reconcile, client, config.budget.id, rows_to_lock)
    except Exception as error:
        view.busy = False
        if classify(error).failure is Failure.TIMED_OUT:
            # The answer was lost, not necessarily the lock: sync to see what YNAB has
            shell.notify(LOCK_TIMED_OUT, "warn")
            state().invalidate()
        else:
            shell.notify(f"Nothing was locked. {ynab_error_message(error)}", "error")
        view.refresh()
        return

    next_date = lock_checkpoint(
        [row.transaction for _, rows in batches for row in rows],
        [row.transaction for group in view.groups for row in group.pending()],
        include_uncleared=view.include_uncleared,
    )
    # YNAB changed: show it, log it and sync before anything that can still fail
    try:
        for _, rows in batches:
            for row in rows:
                row.locked = True
                row.selected = False
                view.locked_ids.add(row.transaction.id)
                view.paint_row(row)
        view.last_locked = count
        state().invalidate()
        message, log_details = lock_log(locked)
        await run.io_bound(state().store.log, config.budget.id, "reconcile", message, log_details)
        if next_date is not None:

            def set_last_reconciliation(saved: LatestConfig) -> None:
                saved.last_reconciliation_date = next_date

            await shell.save_config(set_last_reconciliation)
    finally:
        view.busy = False
        view.refresh()
    shell.notify(f"{plural(count, 'transaction')} locked in YNAB")
