"""Import: Files -> Review -> Done.

Files arrive from the drop zone on this page, from the shell's pending uploads (dropped on
another page) and from drops while the view is on screen. Each one is saved into a temporary
directory owned by the flow, detected on its own (`core.detect`), mapped to its account and
compared with YNAB (`core.importing.build_import_plan`). The review lists what will be
created; one click commits every file in turn (`commit_import_plan`) and logs it.

This is the twin of `yul load auto`, built on the same core calls. The model is in `data`,
the file rows in `rows`, the tables in `tables`.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Sequence
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from nicegui import background_tasks, context, run, ui
from ynab import TransactionClearedStatus

from ynab_unlinked.context_object import YnabUnlinkedContext
from ynab_unlinked.core.detect import Candidate, detect_loaders
from ynab_unlinked.core.importing import (
    ImportPlan,
    ImportResult,
    build_import_plan,
    commit_import_plan,
    share_import_ids,
)
from ynab_unlinked.entities.registry import loaders
from ynab_unlinked.formatter import Formatter
from ynab_unlinked.web import shell
from ynab_unlinked.web.components import set_class
from ynab_unlinked.web.components.dropzone import dropzone
from ynab_unlinked.web.state import state
from ynab_unlinked.web.storage import tab_storage
from ynab_unlinked.web.views.import_.cards import (
    Progress,
    done_card,
    files_footer,
    progress_card,
    review_card,
    review_footer,
)
from ynab_unlinked.web.views.import_.data import (
    STEPS,
    ImportFile,
    Status,
    chosen_accounts,
    import_log,
    parse_file,
    preferred_options,
    problem_text,
)
from ynab_unlinked.web.views.import_.rows import draw_row
from ynab_unlinked.web.wording import plural, ynab_error_message

_FLOW_KEY = "yul.import_flow"


class ImportFlow:
    """One run of the Files -> Review -> Done flow in one browser tab."""

    def __init__(self) -> None:
        self.files: list[ImportFile] = []
        self.rows: dict[int, ui.element] = {}
        self.tempdir: TemporaryDirectory[str] | None = None
        self.step = 0
        self.committing = False
        self.reconciled = False
        self.next_key = 1
        self.account_names: dict[str, str] | None = None
        self.stepper: list[ui.element] = []
        self.content: ui.element | None = None
        self.drop_area: ui.element | None = None
        self.file_list: ui.element | None = None
        self.footer: ui.element | None = None

    # ---- lifecycle -----------------------------------------------------------------------

    def render(self) -> ui.element:
        with ui.element("div").classes("yul-imp") as root:
            with ui.element("div").classes("yul-imp-stepper").mark("stepper"):
                for index, title in enumerate(STEPS):
                    if index:
                        ui.element("div").classes("yul-imp-ln")
                    with ui.element("div").classes("yul-imp-st").mark(f"step-{index + 1}") as st:
                        ui.label(str(index + 1)).classes("num")
                        ui.label(title)
                    self.stepper.append(st)
            self.content = ui.element("div")
        self.show_files()
        return root

    def close(self) -> None:
        """Remove the uploaded files from disk."""
        if self.tempdir is not None:
            self.tempdir.cleanup()
            self.tempdir = None

    def reset(self) -> None:
        self.close()
        self.files = []
        self.rows = {}
        self.committing = False
        self.reconciled = False
        self.show_files()

    def set_step(self, step: int) -> None:
        self.step = step
        for index, element in enumerate(self.stepper):
            set_class(element, "on", index == step)
            set_class(element, "done", index < step)

    def context(self) -> YnabUnlinkedContext[Any]:
        current = state()
        config, _ = current.require()
        return YnabUnlinkedContext(
            config=config, formatter=current.require_formatter(), extras=None
        )

    def formatter(self) -> Formatter:
        return state().require_formatter()

    @property
    def active(self) -> list[ImportFile]:
        return [item for item in self.files if item.status is not Status.UNSUPPORTED]

    @property
    def ready(self) -> list[ImportFile]:
        return [item for item in self.files if item.status is Status.READY]

    # ---- files arriving ------------------------------------------------------------------

    async def add_files(self, uploads: Sequence[shell.UploadedFile]) -> None:
        if not uploads:
            return
        if self.committing:
            shell.notify("Wait for the import to finish before adding files", "warn")
            return
        if self.step == 2:
            self.reset()
        elif self.step == 1:
            self.show_files()

        if self.tempdir is None:
            self.tempdir = TemporaryDirectory(prefix="yul-import-")
        added: list[ImportFile] = []
        for upload in uploads:
            key = self.next_key
            self.next_key += 1
            name = Path(upload.name).name or "statement"
            path = Path(self.tempdir.name) / str(key) / name
            await upload.save(path)
            added.append(ImportFile(key=key, name=name, size=upload.size(), path=path))

        first = not self.files
        self.files.extend(added)
        if first:
            self.draw_drop_area()
        for item in added:
            self.add_row(item)
            # NiceGUI returns the task as a bare `asyncio.Task`
            background_tasks.create(self.detect(item), name=f"yul detect {item.name}")  # pyright: ignore[reportUnknownMemberType]
        self.draw_footer()

    async def detect(self, item: ImportFile) -> None:
        try:
            detections = await run.io_bound(detect_loaders, [item.path], self.context())
        except Exception as error:
            item.status = Status.UNSUPPORTED
            item.problem = f"Could not be read: {error}"
            self.refresh(item)
            return
        if not detections:
            return  # the app is shutting down

        [detection] = detections

        item.detection = detection
        if (best := detection.best) is not None:
            await self.use(item, best)
        elif detection.ambiguous:
            item.status = Status.CHOOSE
            self.refresh(item)
        else:
            item.status = Status.UNSUPPORTED
            item.problem = problem_text(detection, loaders())
            self.refresh(item)

    async def use(self, item: ImportFile, candidate: Candidate) -> None:
        """Take `candidate` for the file: saved options and account, then the plan."""
        config, _ = state().require()
        saved = config.entity(candidate.loader.name)
        if saved is not None and not saved.enabled:
            item.candidate = candidate
            item.status = Status.UNSUPPORTED
            item.problem = f"{candidate.loader.title} is turned off in Settings › Banks"
            self.refresh(item)
            return
        item.version += 1
        previous, item.candidate = item.candidate, candidate
        item.plan = None
        if previous is None or previous.loader != candidate.loader:
            item.account_chosen = False
        if not item.account_chosen:
            item.account_id = saved.account_id if saved else None

        preferred = preferred_options(candidate.options, saved)
        if preferred != dict(candidate.options):
            await self.reparse(item, preferred)
            return
        await self.advance(item)

    async def reparse(self, item: ImportFile, options: dict[str, str]) -> None:
        """Read the file again with other option values (a select on the row changed)."""
        if item.candidate is None:
            return
        item.version += 1
        version = item.version
        item.status = Status.PLANNING
        item.plan = None
        self.refresh(item)
        spec = item.candidate.loader
        try:
            transactions = await run.io_bound(parse_file, spec, item.path, options, self.context())
        except Exception as error:
            if version != item.version:
                return
            item.candidate = dataclasses.replace(
                item.candidate, options=options, transactions=None, error=str(error)
            )
        else:
            if version != item.version:
                return
            item.candidate = dataclasses.replace(
                item.candidate, options=options, transactions=tuple(transactions or ()), error=None
            )
        await self.advance(item)

    async def advance(self, item: ImportFile) -> None:
        """Build the plan once the file has transactions and an account."""
        candidate = item.candidate
        if candidate is None:
            return
        if candidate.transactions is None:
            item.status = Status.ERROR
            item.problem = f"{candidate.loader.title} could not read it: {candidate.error}"
            self.refresh(item)
            return
        # Loaded once: the names of the accounts on every row, and the choices when one is missing
        await self.account_choices()
        if item.account_id is None:
            item.status = Status.ACCOUNT
            self.refresh(item)
            return

        config, client = state().require()
        item.version += 1
        version = item.version
        item.status = Status.PLANNING
        item.plan = None
        self.refresh(item)
        try:
            plan = await run.io_bound(
                build_import_plan,
                client,
                config.budget.id,
                item.account_id,
                candidate.loader.name,
                item.path,
                list(candidate.transactions),
            )
        except Exception as error:
            if version != item.version:
                return
            item.status = Status.ERROR
            item.problem = ynab_error_message(error)
            self.refresh(item)
            return
        if plan is None or version != item.version:
            return
        item.plan = plan
        item.status = Status.READY
        item.problem = None
        self.refresh(item)

    async def account_choices(self) -> dict[str, str]:
        """Accounts a file can go to: every open account of the budget."""
        if self.account_names is None:
            try:
                accounts = await state().budget_accounts()
            except Exception as error:
                shell.notify(ynab_error_message(error), "warn")
                accounts = []
            self.account_names = {a.id: a.name for a in accounts if not a.closed}
        return self.account_names

    def account_name(self, account_id: str) -> str:
        if (name := (self.account_names or {}).get(account_id)) is not None:
            return name
        config, _ = state().require()
        if (account := config.account(account_id)) is not None:
            return account.name
        return account_id

    # ---- row actions ---------------------------------------------------------------------

    async def pick_account(self, item: ImportFile, account_id: str | None) -> None:
        if not account_id:
            return
        item.account_id = account_id
        item.account_chosen = True
        await self.advance(item)

    async def change_option(self, item: ImportFile, key: str, value: str) -> None:
        if item.candidate is None or item.candidate.options.get(key) == value:
            return
        await self.reparse(item, {**item.candidate.options, key: value})

    def remove(self, item: ImportFile) -> None:
        item.version += 1
        if item in self.files:
            self.files.remove(item)
        if (row := self.rows.pop(item.key, None)) is not None:
            row.delete()
        if not self.files:
            self.reset()
            return
        self.draw_footer()

    def toggle(self, item: ImportFile) -> None:
        item.open = not item.open
        if (row := self.rows.get(item.key)) is not None:
            set_class(row, "open", item.open)

    # ---- step 1: files -------------------------------------------------------------------

    def show_files(self) -> None:
        self.set_step(0)
        assert self.content is not None
        self.content.clear()
        self.rows = {}
        with self.content:
            self.drop_area = ui.element("div")
            self.file_list = ui.element("div").classes("yul-imp-files").mark("import-files")
            self.footer = ui.element("div")
        self.draw_drop_area()
        for item in self.files:
            self.add_row(item)
        self.draw_footer()

    def draw_drop_area(self) -> None:
        if self.drop_area is None:
            return
        self.drop_area.clear()
        with self.drop_area:
            dropzone(self.add_files, compact=bool(self.files))

    def add_row(self, item: ImportFile) -> None:
        assert self.file_list is not None
        with self.file_list:
            row = ui.element("div").classes("yul-imp-file").mark(f"file-{item.key}")
        self.rows[item.key] = row
        draw_row(self, item)

    def refresh(self, item: ImportFile) -> None:
        if self.step == 0 and item in self.files:
            draw_row(self, item)
            self.draw_footer()

    def draw_footer(self) -> None:
        if self.footer is None or self.step != 0:
            return
        self.footer.clear()
        if not self.files:
            return
        with self.footer:
            files_footer(self.files, self.active, self.ready, self.show_review)

    # ---- step 2: review ------------------------------------------------------------------

    def show_review(self) -> None:
        ready = self.ready
        if not ready or any(item.blocking for item in self.files):
            return
        # Files for one account are numbered as one, or their identical rows would collide
        planned = [(item, item.plan) for item in ready if item.plan is not None]
        shared = share_import_ids([plan for _, plan in planned])
        for (item, _), plan in zip(planned, shared, strict=True):
            item.plan = plan
        self.set_step(1)
        assert self.content is not None
        self.content.clear()
        self.footer = None
        with self.content, ui.element("div").classes("yul-stagger"):
            for item in ready:
                assert item.plan is not None
                review_card(item, self.account_name(item.plan.account_id), self.formatter())
        with self.content:
            review_footer(
                ready,
                reconciled=self.reconciled,
                on_reconciled=lambda on: setattr(self, "reconciled", on),
                on_back=self.show_files,
                on_import=self.commit,
            )

    # ---- step 3: done --------------------------------------------------------------------

    async def commit(self) -> None:
        if self.committing:
            return
        ready = [item for item in self.ready if item.plan is not None]
        self.committing = True
        self.save_accounts(ready)
        config, client = state().require()
        cleared = (
            TransactionClearedStatus.RECONCILED
            if self.reconciled
            else TransactionClearedStatus.CLEARED
        )

        self.set_step(2)
        assert self.content is not None
        self.content.clear()
        progress: dict[int, Progress] = {}
        with self.content:
            for item in ready:
                assert item.plan is not None
                progress[item.key] = progress_card(item, self.account_name(item.plan.account_id))
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
                result = await run.io_bound(
                    commit_import_plan, client, config.budget.id, plan, cleared
                )
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
            await self.log(item, plan, result)

        self.committing = False
        self.close()
        with done_area:
            done_card(created, duplicates, skipped, failed, self.reset)
        if created:
            # Reconcile and Net worth sync before showing the store again
            state().invalidate()
            shell.notify(f"{plural(created, 'transaction')} created in YNAB")

    def save_accounts(self, items: Sequence[ImportFile]) -> None:
        if not (chosen := chosen_accounts(items)):
            return

        with shell.edit_config() as config:
            for name, account_id in chosen:
                config.set_entity_account(name, account_id)
        for item in items:
            item.account_chosen = False

    async def log(self, item: ImportFile, plan: ImportPlan, result: ImportResult) -> None:
        config, _ = state().require()
        assert item.candidate is not None
        message, details = import_log(
            item.candidate.loader.name,
            item.name,
            self.account_name(plan.account_id),
            plan,
            result,
        )
        try:
            await run.io_bound(state().store.log, config.budget.id, "import", message, details)
        except Exception as error:
            shell.notify(f"Could not record the import in the activity log: {error}", "warn")


@shell.view(
    shell.IMPORT_PATH,
    key="import",
    title="Import",
    subtitle="Files → Review → Done",
    icon="import",
    order=20,
    live=False,
)
async def import_view() -> None:
    storage = tab_storage()
    if isinstance(previous := storage.get(_FLOW_KEY), ImportFlow):
        previous.close()
    flow = ImportFlow()
    storage[_FLOW_KEY] = flow
    # NiceGUI types the handler as a bare `Callable`
    context.client.on_delete(flow.close)  # pyright: ignore[reportUnknownMemberType]

    root = flow.render()
    shell.on_drop(flow.add_files, owner=root)
    if pending := shell.pending_uploads():
        await flow.add_files(pending)
