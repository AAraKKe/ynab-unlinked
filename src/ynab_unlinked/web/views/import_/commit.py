"""Import, step Done: commit every reviewed file to YNAB in turn and log each one.

Moved out of `view` so the flow stays readable; `ImportFlow.commit` calls `commit` here.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

from nicegui import run, ui
from ynab import TransactionClearedStatus

from ynab_unlinked.config import LatestConfig
from ynab_unlinked.core.importing import ImportPlan, ImportResult, commit_import_plan
from ynab_unlinked.web import shell
from ynab_unlinked.web.state import state
from ynab_unlinked.web.views.import_.cards import Progress, done_card, progress_card
from ynab_unlinked.web.views.import_.data import ImportFile, chosen_accounts, import_log
from ynab_unlinked.web.wording import IMPORT_FAILED, plural, ynab_error_message

if TYPE_CHECKING:
    from ynab_unlinked.web.views.import_.view import ImportFlow


async def commit(flow: ImportFlow) -> None:
    if flow.committing:
        return
    ready = [item for item in flow.ready if item.plan is not None]
    flow.committing = True
    try:
        await commit_files(flow, ready)
    except Exception:
        # The import button that started the commit is gone with the review
        assert flow.content is not None
        with flow.content:
            shell.notify(IMPORT_FAILED, "error")
    finally:
        flow.committing = False


async def commit_files(flow: ImportFlow, ready: Sequence[ImportFile]) -> None:
    await save_accounts(ready)
    config, client = state().require()
    cleared = (
        TransactionClearedStatus.RECONCILED if flow.reconciled else TransactionClearedStatus.CLEARED
    )

    flow.set_step(2)
    assert flow.content is not None
    flow.content.clear()
    progress: dict[int, Progress] = {}
    with flow.content:
        for item in ready:
            assert item.plan is not None
            progress[item.key] = progress_card(item, flow.account_name(item.plan.account_id))
        done_area = ui.element("div")

    created = duplicates = skipped = failed = 0
    for item in ready:
        assert item.plan is not None and item.candidate is not None
        plan = item.plan
        card = progress[item.key]
        skipped += plan.already_imported_count
        if not plan.new_rows:
            card.nothing_new()
            continue
        card.running()
        try:
            result = await run.io_bound(commit_import_plan, client, config.budget.id, plan, cleared)
        except Exception as error:
            failed += 1
            message = ynab_error_message(error)
            card.failed(message)
            shell.notify(f"{item.name}: {message}", "error")
            continue
        if result is None:
            return  # the app is shutting down

        created += result.created
        duplicates += len(result.duplicate_import_ids)
        card.created(result)
        await log(flow, item, plan, result)

    flow.close()
    with done_area:
        done_card(created, duplicates, skipped, failed, flow.reset)
    if created:
        # Reconcile and Net worth sync before showing the store again
        state().invalidate()
        shell.notify(f"{plural(created, 'transaction')} created in YNAB")


async def save_accounts(items: Sequence[ImportFile]) -> None:
    if not (chosen := chosen_accounts(items)):
        return

    def set_accounts(config: LatestConfig) -> None:
        for name, account_id in chosen:
            config.set_entity_account(name, account_id)

    await shell.save_config(set_accounts)
    for item in items:
        item.account_chosen = False


async def log(flow: ImportFlow, item: ImportFile, plan: ImportPlan, result: ImportResult) -> None:
    config, _ = state().require()
    assert item.candidate is not None
    message, details = import_log(
        item.candidate.loader.name,
        item.name,
        flow.account_name(plan.account_id),
        plan,
        result,
    )
    try:
        await run.io_bound(state().store.log, config.budget.id, "import", message, details)
    except Exception as error:
        shell.notify(f"Could not record the import in the activity log: {error}", "warn")
