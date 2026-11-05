"""Import: Files -> Review -> Done.

Files arrive from the drop zone on this page, from the shell's pending uploads (dropped on
another page) and from drops while the view is on screen. Each one is saved into a temporary
directory owned by the flow, detected on its own (`core.detect`), mapped to its account and
compared with YNAB (`core.importing.build_import_plan`). The review lists what will be
created; one click commits every file in turn (`commit_import_plan`) and logs it.

This is the twin of `yul load auto`, built on the same core calls.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from nicegui import background_tasks, context, run, ui
from ynab import TransactionClearedStatus

from ynab_unlinked.context_object import YnabUnlinkedContext
from ynab_unlinked.core.detect import Candidate, Detection, detect_loaders
from ynab_unlinked.core.importing import (
    ImportPlan,
    ImportResult,
    build_import_plan,
    commit_import_plan,
    parse_transactions,
)
from ynab_unlinked.entities.registry import AUTO, LoaderOption, LoaderSpec, loaders
from ynab_unlinked.formatter import Formatter
from ynab_unlinked.models import Transaction
from ynab_unlinked.web import shell
from ynab_unlinked.web.components import bank_logo, button, check, glass_card, pill, spinner
from ynab_unlinked.web.components.dropzone import dropzone
from ynab_unlinked.web.state import state
from ynab_unlinked.web.views.onboarding import ynab_error_message
from ynab_unlinked.web.views.settings import human_size

STEPS = ("Files", "Review", "Done")
FILE_COLORS = {
    "xlsx": "#1f8a5b",
    "xls": "#1f8a5b",
    "txt": "#5b63d6",
    "html": "#c2622a",
    "pdf": "#c2413a",
}
OTHER_FILE_COLOR = "#64748b"
YEARS_OFFERED = 3

_FLOW_KEY = "yul.import_flow"
_CSS_KEY = "yul.import.css"
_CSS = """
.yul-imp { width: 100%; }
.yul-imp-stepper { display: flex; align-items: center; gap: 8px; margin-bottom: 16px; }
.yul-imp-st { display: flex; align-items: center; gap: 8px; color: var(--text-3); font-weight: 500; font-size: 13px; }
.yul-imp-st > .num {
  width: 24px; height: 24px; border-radius: 50%; display: grid; place-items: center; font-size: 12px;
  border: 1px solid var(--border-2); transition: all .2s;
}
.yul-imp-st.on { color: var(--text); }
.yul-imp-st.on > .num { background: var(--accent); border-color: transparent; color: #fff; }
.yul-imp-st.done { color: var(--text-2); }
.yul-imp-st.done > .num {
  background: color-mix(in oklab, var(--good) 20%, transparent); border-color: var(--good); color: var(--good);
}
.yul-imp-ln { flex: 1; height: 1px; background: var(--border-2); max-width: 60px; }
.yul-imp-files { display: flex; flex-direction: column; gap: 8px; margin-top: 12px; }
.yul-imp-file {
  border: 1px solid var(--border); border-radius: 14px; background: var(--surface); overflow: hidden;
  backdrop-filter: blur(12px); -webkit-backdrop-filter: blur(12px); animation: yul-enter .35s var(--ease) both;
  transition: opacity .2s;
}
.yul-imp-file.off { opacity: .55; }
.yul-imp-head { display: flex; align-items: center; gap: 12px; padding: 12px 14px; cursor: pointer; }
.yul-imp-badge {
  width: 38px; height: 38px; border-radius: 11px; display: grid; place-items: center; font-size: 10px;
  font-weight: 800; color: #fff; flex: none; letter-spacing: .04em;
}
.yul-imp-badge.sm { width: 30px; height: 30px; border-radius: 9px; font-size: 9px; }
.yul-imp-name { font-weight: 500; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.yul-imp-meta { color: var(--text-3); font-size: 12px; }
.yul-imp-det {
  display: flex; align-items: center; gap: 8px; justify-content: flex-end; flex-wrap: wrap; cursor: default;
}
.yul-imp-reason { color: var(--text-3); font-size: 12px; max-width: 320px; text-align: right; }
.yul-imp-arrow { transition: transform .2s; color: var(--text-3); font-size: 18px; width: 12px; }
.yul-imp-file.open .yul-imp-arrow { transform: rotate(90deg); }
.yul-imp-body {
  display: none; border-top: 1px solid var(--border); padding: 12px 14px 14px; background: rgba(0, 0, 0, .12);
}
body.body--light .yul-imp-body { background: rgba(15, 23, 42, .03); }
.yul-imp-file.open .yul-imp-body { display: block; animation: yul-enter .25s var(--ease) both; }
.yul-imp-seg { display: inline-flex; border: 1px solid var(--border-2); border-radius: 9px; overflow: hidden; }
.yul-imp-seg > .opt { padding: 4px 10px; font-size: 12px; color: var(--text-2); cursor: pointer; transition: all .15s; }
.yul-imp-seg > .opt + .opt { border-left: 1px solid var(--border); }
.yul-imp-seg > .opt:hover { color: var(--text); }
.yul-imp-seg > .opt.on { background: var(--surface-2); color: var(--text); }
.yul-imp-det .q-field { min-width: 92px; }
.yul-imp-det .yul-bank-logo { padding: 0 6px; }
.yul-imp-det .q-field--dense .q-field__control,
.yul-imp-det .q-field--dense .q-field__marginal { min-height: 30px; height: 30px; }
.yul-imp-det .q-field--dense .q-field__native { min-height: 30px; padding: 0; font-size: 12.5px; }
.yul-imp-det .q-field--dense .q-field__label { top: 6px; font-size: 12.5px; }
.yul-imp-det .q-field--float .q-field__label { display: none; }
.yul-imp-det .q-field--labeled .q-field__control-container,
.yul-imp-det .q-field--labeled .q-field__native { padding-top: 0; }
.yul-imp-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.yul-imp-table th {
  text-align: left; font-weight: 500; color: var(--text-3); padding: 6px 8px; border-bottom: 1px solid var(--border);
  font-size: 11.5px; text-transform: uppercase; letter-spacing: .04em;
}
.yul-imp-table td { padding: 7px 8px; border-bottom: 1px solid var(--hair); }
.yul-imp-table tr:last-child td { border-bottom: 0; }
.yul-imp-table .r { text-align: right; }
.yul-imp-table td.num { font-variant-numeric: tabular-nums; white-space: nowrap; }
.yul-imp-table tr.dim td { color: var(--text-3); }
.yul-imp-note { color: var(--text-2); font-size: 12.5px; margin-bottom: 8px; }
.yul-imp-sticky {
  position: sticky; bottom: 12px; margin-top: 16px; display: flex; align-items: center; gap: 14px;
  padding: 12px 16px; border-radius: 14px; border: 1px solid var(--border-2); z-index: 4;
  background: color-mix(in oklab, var(--bg) 70%, transparent); backdrop-filter: blur(18px);
  -webkit-backdrop-filter: blur(18px); box-shadow: 0 -10px 30px -20px rgba(0, 0, 0, .6);
}
.yul-imp-stat { display: flex; gap: 16px; flex-wrap: wrap; align-items: center; }
.yul-imp-stat b { font-weight: 600; }
.yul-imp-card { margin-bottom: 10px; padding: 14px 16px; }
.yul-imp-done { text-align: center; padding: 28px; }
"""


class Status(StrEnum):
    DETECTING = "detecting"
    CHOOSE = "choose"
    """Several loaders read the file, the user picks one."""
    ACCOUNT = "account"
    """The loader has no account yet, the user picks one."""
    PLANNING = "planning"
    READY = "ready"
    ERROR = "error"
    """A loader was chosen but the file could not be read with it, or YNAB failed."""
    UNSUPPORTED = "unsupported"
    """No loader reads the file. Kept, greyed, and ignored."""


@dataclass(eq=False)
class ImportFile:
    key: int
    name: str
    size: int
    path: Path
    status: Status = Status.DETECTING
    detection: Detection | None = None
    candidate: Candidate | None = None
    account_id: str | None = None
    account_chosen: bool = False
    """Picked on the row: saved to the config when the import is confirmed."""
    plan: ImportPlan | None = None
    problem: str | None = None
    open: bool = False
    version: int = 0
    """Bumped on every change, so an answer for an older state is dropped."""

    @property
    def suffix(self) -> str:
        return self.path.suffix[1:].lower()

    @property
    def blocking(self) -> bool:
        return self.status not in (Status.READY, Status.UNSUPPORTED)


def file_color(suffix: str) -> str:
    return FILE_COLORS.get(suffix, OTHER_FILE_COLOR)


def problem_text(detection: Detection, specs: Sequence[LoaderSpec]) -> str:
    """Why a file without a usable loader cannot be imported."""
    if detection.candidates:
        errors = "; ".join(f"{c.loader.title}: {c.error}" for c in detection.candidates)
        return f"Could not be read. {errors}"
    if readers := [spec.title for spec in specs if spec.accepts(detection.input_file)]:
        return f"Does not look like a statement from {', '.join(readers)}"
    supported = sorted({str(t.value) for spec in specs for t in spec.input_types})
    return f"No bank exports this kind of file. Supported: {', '.join(supported)}"


def option_choices(option: LoaderOption, current: str, today: dt.date) -> list[str]:
    if option.choices:
        return [choice for choice in option.choices if choice != AUTO]
    if option.key == "year":
        years = [str(today.year - offset) for offset in range(YEARS_OFFERED)]
        return years if current in years else [current, *years]
    return [current]


def plural(count: int, word: str) -> str:
    return f"{count} {word}{'' if count == 1 else 's'}"


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
            element.classes(remove="on done")
            if index == step:
                element.classes(add="on")
            elif index < step:
                element.classes(add="done")

    def context(self) -> YnabUnlinkedContext[Any]:
        current = state()
        config, _ = current.require()
        formatter = current.formatter or Formatter(
            date_format=config.budget.date_format, currency_format=config.budget.currency_format
        )
        return YnabUnlinkedContext(config=config, formatter=formatter, extras=None)

    def formatter(self) -> Formatter:
        return self.context().formatter

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
            background_tasks.create(self.detect(item), name=f"yul detect {item.name}")
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

        preferred = dict(candidate.options)
        for key, value in (saved.options if saved else {}).items():
            if key in preferred and value != AUTO:
                preferred[key] = value
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
            transactions = await run.io_bound(self.parse, spec, item.path, options)
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

    def parse(self, spec: LoaderSpec, path: Path, options: dict[str, str]) -> list[Transaction]:
        base = self.context()
        context = dataclasses.replace(base, extras=spec.context_extras(options))
        return parse_transactions(spec.build(options), path, context)

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

    async def choose(self, item: ImportFile, candidate: Candidate) -> None:
        await self.use(item, candidate)

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

    async def retry(self, item: ImportFile) -> None:
        await self.advance(item)

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
            if item.open:
                row.classes(add="open")
            else:
                row.classes(remove="open")

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
        self.draw_row(item)

    def refresh(self, item: ImportFile) -> None:
        if self.step == 0 and item in self.files:
            self.draw_row(item)
            self.draw_footer()

    def draw_row(self, item: ImportFile) -> None:
        row = self.rows.get(item.key)
        if row is None or row.is_deleted:
            return
        row.clear()
        if item.status is Status.UNSUPPORTED:
            row.classes(add="off")
        else:
            row.classes(remove="off")
        with row:
            with ui.element("div").classes("yul-imp-head") as head:
                self.badge(item.suffix)
                with ui.element("div").classes("yul-grow"):
                    ui.label(item.name).classes("yul-imp-name")
                    ui.label(human_size(item.size)).classes("yul-imp-meta")
                with ui.element("div").classes("yul-imp-det") as det:
                    self.draw_detection(item)
                det.on("click", js_handler="(e) => e.stopPropagation()")
                ui.label("›").classes("yul-imp-arrow")
            head.on("click", lambda: self.toggle(item))
            with ui.element("div").classes("yul-imp-body"):
                self.draw_body(item)

    def badge(self, suffix: str, *, small: bool = False) -> None:
        badge = ui.label((suffix or "?").upper()[:4]).classes("yul-imp-badge")
        badge.style(f"background:{file_color(suffix)}")
        if small:
            badge.classes(add="sm")

    def draw_detection(self, item: ImportFile) -> None:
        match item.status:
            case Status.DETECTING:
                spinner()
                ui.label("Detecting…").classes("yul-muted")
                return
            case Status.UNSUPPORTED:
                ui.label(item.problem or "Not supported").classes("yul-imp-reason").mark(
                    f"problem-{item.key}"
                )
                self.remove_button(item)
                return
            case _:
                pass

        detection = item.detection
        if detection is not None and detection.ambiguous:
            self.draw_choice(item, detection)
        candidate = item.candidate
        if candidate is None:
            self.remove_button(item)
            return

        if detection is None or not detection.ambiguous:
            bank_logo(candidate.loader.key, candidate.loader.title, size=26)
            pill(f"{candidate.loader.title} · {candidate.confidence:.0%}", "ok").mark(
                f"loader-{item.key}"
            )
        # Every option of the bank, starting from the saved defaults, changeable per file
        for option in candidate.loader.options:
            self.option_select(item, candidate, option)
        self.draw_account(item)

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
                    button("Retry", small=True, on_click=lambda: self.retry(item)).mark(
                        f"retry-{item.key}"
                    )
            case _:
                pass
        self.remove_button(item)

    def draw_choice(self, item: ImportFile, detection: Detection) -> None:
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
                option.on("click", lambda _, c=candidate: self.choose(item, c))

    def option_select(self, item: ImportFile, candidate: Candidate, option: LoaderOption) -> None:
        current = candidate.options.get(option.key, "")
        select = ui.select(
            option_choices(option, current, dt.date.today()), value=current or None
        ).props("outlined dense options-dense")
        select.props["title"] = option.label
        select.mark(f"option-{item.key}-{option.key}")
        select.on_value_change(
            lambda e, key=option.key: self.change_option(item, key, str(e.value))
        )

    def draw_account(self, item: ImportFile) -> None:
        if item.account_id is not None and not item.account_chosen:
            pill(f"→ {self.account_name(item.account_id)}").mark(f"account-{item.key}")
            return
        select = ui.select(self.account_names or {}, value=item.account_id, label="Account").props(
            "outlined dense options-dense"
        )
        select.style("min-width:170px").mark(f"account-select-{item.key}")
        select.on_value_change(lambda e: self.pick_account(item, e.value))

    def remove_button(self, item: ImportFile) -> None:
        remove = button(icon_name="x", kind="ghost", small=True, on_click=lambda: self.remove(item))
        remove.props["title"] = "Remove"
        remove.mark(f"remove-{item.key}")

    def draw_body(self, item: ImportFile) -> None:
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
            self.table(item.plan)
        elif candidate.transactions is not None:
            self.transactions_table(candidate.transactions)

    def table(self, plan: ImportPlan) -> None:
        formatter = self.formatter()
        with ui.element("table").classes("yul-imp-table"):
            self.table_header()
            for row in plan.rows:
                with ui.element("tr") as tr:
                    self.cells(row.transaction, formatter)
                    with ui.element("td").classes("r"):
                        if row.already_imported:
                            ui.label("already in YNAB")
                        else:
                            pill("new", "ok")
                if row.already_imported:
                    tr.classes(add="dim")
        if plan.rows:
            ui.label(
                "Rows already in YNAB are matched by import id and are never sent twice."
            ).classes("yul-faint yul-small").style("margin-top:6px")

    def transactions_table(self, transactions: Sequence[Transaction]) -> None:
        formatter = self.formatter()
        with ui.element("table").classes("yul-imp-table"):
            self.table_header()
            for transaction in transactions:
                with ui.element("tr"):
                    self.cells(transaction, formatter)
                    with ui.element("td").classes("r"):
                        ui.label("…").classes("yul-faint")

    def table_header(self) -> None:
        with ui.element("tr"):
            for title, align in (("Date", ""), ("Payee", ""), ("Amount", "r"), ("Status", "r")):
                with ui.element("th").classes(align):
                    ui.label(title)

    def cells(self, transaction: Transaction, formatter: Formatter) -> None:
        with ui.element("td").classes("num"):
            ui.label(formatter.format_date(transaction.date))
        with ui.element("td"):
            ui.label(transaction.payee)
        with ui.element("td").classes("r num"):
            ui.label(formatter.format_amount(transaction.amount))

    def draw_footer(self) -> None:
        if self.footer is None or self.step != 0:
            return
        self.footer.clear()
        if not self.files:
            return
        ready = self.ready
        blocked = any(item.blocking for item in self.files)
        transactions = sum(len(item.plan.rows) for item in ready if item.plan)
        new = sum(len(item.plan.new_rows) for item in ready if item.plan)
        with self.footer, ui.element("div").classes("yul-imp-sticky").mark("files-footer"):
            with ui.element("div").classes("yul-grow yul-imp-stat"):
                ui.label(plural(len(self.active), "file"))
                ui.label(plural(transactions, "transaction"))
                ui.label(f"{new} new").classes("yul-good")
                ui.label(f"{transactions - new} already in YNAB").classes("yul-muted")
                if unsupported := len(self.files) - len(self.active):
                    ui.label(f"{plural(unsupported, 'file')} skipped").classes("yul-faint")
            review = button(
                f"Review {plural(len(ready), 'file')}", kind="primary", on_click=self.show_review
            ).mark("review")
            if blocked or not ready:
                review.disable()

    # ---- step 2: review ------------------------------------------------------------------

    def show_review(self) -> None:
        ready = self.ready
        if not ready or any(item.blocking for item in self.files):
            return
        self.set_step(1)
        assert self.content is not None
        self.content.clear()
        self.footer = None
        new = sum(len(item.plan.new_rows) for item in ready if item.plan)
        accounts = {item.account_id for item in ready if item.plan and item.plan.new_rows}
        with self.content, ui.element("div").classes("yul-stagger"):
            for item in ready:
                assert item.plan is not None and item.candidate is not None
                with glass_card().classes("yul-imp-card").mark(f"review-{item.key}"):
                    with ui.element("div").classes("yul-row").style("margin-bottom:8px"):
                        self.badge(item.suffix, small=True)
                        ui.label(item.candidate.loader.title).style("font-weight:600")
                        pill(f"→ {self.account_name(item.plan.account_id)}")
                        ui.label(item.name).classes("yul-faint yul-small")
                        ui.element("span").classes("yul-grow")
                        pill(f"{len(item.plan.new_rows)} new / {len(item.plan.rows)}", "acc").mark(
                            f"review-count-{item.key}"
                        )
                    self.table(item.plan)
        with self.content, ui.element("div").classes("yul-imp-sticky").mark("review-footer"):
            with ui.element("div").classes("yul-grow yul-imp-stat"):
                ui.label(
                    f"{plural(new, 'new transaction')} in {plural(len(accounts), 'account')}"
                ).style("font-weight:600").mark("review-summary")
                reconciled = ui.switch("import as reconciled", value=self.reconciled)
                reconciled.mark("reconciled")
                reconciled.on_value_change(lambda e: setattr(self, "reconciled", bool(e.value)))
            button("Back", kind="ghost", on_click=self.show_files).mark("back")
            go = button(
                f"Import {plural(new, 'transaction')}", kind="primary", on_click=self.commit
            ).mark("import")
            if not new:
                go.disable()

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
        progress: dict[int, tuple[ui.element, ui.element, ui.element]] = {}
        with self.content:
            for item in ready:
                assert item.plan is not None
                with glass_card().classes("yul-imp-card").mark(f"progress-{item.key}"):
                    with ui.element("div").classes("yul-row").style("margin-bottom:8px"):
                        ui.label(self.account_name(item.plan.account_id)).style("font-weight:600")
                        ui.label(
                            f"{plural(len(item.plan.new_rows), 'transaction')} · {item.name}"
                        ).classes("yul-muted")
                        ui.element("span").classes("yul-grow")
                        status = ui.element("div").classes("yul-row yul-small")
                    with status:
                        ui.label("waiting" if item.plan.new_rows else "nothing new").classes(
                            "yul-muted"
                        )
                    with ui.element("div").classes("yul-prog") as bar:
                        fill = ui.element("i").style("width:0%")
                progress[item.key] = (status, bar, fill)
            done_area = ui.element("div")

        created = duplicates = skipped = failed = 0
        for item in ready:
            assert item.plan is not None and item.candidate is not None
            plan = item.plan
            status, bar, fill = progress[item.key]
            skipped += plan.already_imported_count
            if not plan.new_rows:
                fill.style("width:100%")
                continue
            status.clear()
            with status:
                spinner()
            bar.classes(add="active")
            fill.style("width:60%")
            try:
                result = await run.io_bound(
                    commit_import_plan, client, config.budget.id, plan, cleared
                )
            except Exception as error:
                failed += 1
                message = ynab_error_message(error)
                bar.classes(remove="active")
                fill.style("width:100%;background:var(--bad)")
                status.clear()
                with status:
                    ui.label(message).classes("yul-bad").mark(f"commit-error-{item.key}")
                shell.notify(f"{item.name}: {message}", "error")
                continue
            if result is None:
                return  # the app is shutting down

            created += result.created
            duplicates += len(result.duplicate_import_ids)
            bar.classes(remove="active")
            fill.style("width:100%")
            status.clear()
            with status:
                text = f"{result.created} created"
                if result.duplicate_import_ids:
                    text += f" · {plural(len(result.duplicate_import_ids), 'duplicate')}"
                ui.label(text).classes("yul-good")
            await self.log(item, plan, result)

        self.committing = False
        self.close()
        with done_area:
            self.done_card(created, duplicates, skipped, failed)
        if created:
            # Reconcile and Net worth sync before showing the store again
            state().invalidate()
            shell.notify(f"{plural(created, 'transaction')} created in YNAB")

    def save_accounts(self, items: Sequence[ImportFile]) -> None:
        chosen = [
            (item.candidate.loader.name, item.account_id)
            for item in items
            if item.candidate and item.account_chosen and item.account_id
        ]
        if not chosen:
            return
        config, _ = state().require()
        updated = config.model_copy(deep=True)
        for name, account_id in chosen:
            updated.set_entity_account(name, account_id)
        updated.save()
        state().reload()
        for item in items:
            item.account_chosen = False

    async def log(self, item: ImportFile, plan: ImportPlan, result: ImportResult) -> None:
        config, _ = state().require()
        assert item.candidate is not None
        account_name = self.account_name(plan.account_id)
        details = {
            "loader": item.candidate.loader.key,
            "account_id": plan.account_id,
            "account_name": account_name,
            "file": item.name,
            "created": result.created,
            "duplicates": len(result.duplicate_import_ids),
            "skipped": plan.already_imported_count,
        }
        try:
            await run.io_bound(
                state().store.log,
                config.budget.id,
                "import",
                f"Imported {result.created} transactions to {account_name} from {item.name}",
                details,
            )
        except Exception as error:
            shell.notify(f"Could not record the import in the activity log: {error}", "warn")

    def done_card(self, created: int, duplicates: int, skipped: int, failed: int) -> None:
        with glass_card().classes("yul-imp-done").mark("done-card"):
            check(big=True)
            ui.label(f"{plural(created, 'transaction')} imported").classes("yul-h2").mark(
                "done-title"
            )
            lede = (
                f"YNAB rejected {duplicates} as duplicate{'' if duplicates == 1 else 's'}. "
                f"{skipped} {'was' if skipped == 1 else 'were'} already there and "
                f"{'was' if skipped == 1 else 'were'} skipped."
            )
            if failed:
                lede += f" {plural(failed, 'file')} failed, see above."
            ui.label(lede).classes("yul-lede").mark("done-summary")
            with ui.element("div").classes("yul-row").style("justify-content:center"):
                button(
                    "Reconcile these accounts",
                    kind="primary",
                    on_click=lambda: ui.navigate.to("/reconcile"),
                ).mark("reconcile")
                button("Import more", on_click=self.reset).mark("import-more")


def _install_css() -> None:
    storage = context.client.storage
    if not storage.get(_CSS_KEY):
        ui.add_css(_CSS)
        storage[_CSS_KEY] = True


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
    _install_css()
    storage = context.client.storage
    if isinstance(previous := storage.get(_FLOW_KEY), ImportFlow):
        previous.close()
    flow = ImportFlow()
    storage[_FLOW_KEY] = flow
    context.client.on_delete(flow.close)

    root = flow.render()
    shell.on_drop(flow.add_files, owner=root)
    if pending := shell.pending_uploads():
        await flow.add_files(pending)
