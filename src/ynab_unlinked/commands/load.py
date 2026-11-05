from __future__ import annotations

import dataclasses
import importlib
import pkgutil
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any

import typer

from ynab_unlinked import display, entities
from ynab_unlinked.setup import ensure_config

if TYPE_CHECKING:
    from rich.table import Table

    from ynab_unlinked.context_object import YnabUnlinkedContext
    from ynab_unlinked.core.detect import Candidate, Detection
    from ynab_unlinked.core.importing import ImportPlan
    from ynab_unlinked.models import Transaction

load = typer.Typer(
    help="Load transactions from a bank statement into your YNAB account.",
)


@load.callback()
def load_callback(
    context: typer.Context,
    show: Annotated[
        bool,
        typer.Option(
            "-s",
            "--show",
            help="Just show the transactions available in the input file.",
        ),
    ] = False,
    reconcile: Annotated[
        bool,
        typer.Option(
            "-r", "--reconcile", help="Import transactions as reconciled instead of cleared."
        ),
    ] = False,
    account: Annotated[
        bool,
        typer.Option("-a", "--acount", help="Prompt to select the account to load transactions to"),
    ] = False,
    buffer: Annotated[
        int,
        typer.Option(
            "-b",
            "--buffer",
            help=(
                "The number of days before the earliest transaction in the input file to load transactions from YNAB. "
                "This is used to compare your transactions to import with the ones laready in YNAB"
            ),
            show_default=True,
        ),
    ] = 15,
    yes: Annotated[
        bool,
        typer.Option(
            "--yes",
            help=(
                "Import without asking for confirmation, for use without a terminal. Exits with an "
                "error instead of prompting when an answer is needed: there is no config yet, the "
                "entity has no saved account, or --acount is used."
            ),
        ),
    ] = False,
):
    if yes and account:
        display.error("--yes cannot be used with -a/--acount: selecting an account needs a prompt.")
        raise typer.Exit(1)

    obj = ensure_config(context, interactive=not yes)

    obj.yes = yes
    obj.show = show
    obj.reconcile = reconcile
    obj.choose_account = account
    obj.buffer = buffer


def auto(
    context: typer.Context,
    files: Annotated[
        list[Path],
        typer.Argument(
            exists=True,
            file_okay=True,
            dir_okay=False,
            readable=True,
            help="Statement files to import, from any of the supported banks.",
        ),
    ],
):
    """
    Import statements from any supported bank, finding out which bank each file comes from.

    Every file is matched to the bank that exported it and to its options (the language of
    a Cobee page, the year of a Sabadell statement). Files that no bank reads, or that more
    than one could, stop the import before anything is sent to YNAB: import those with
    `yul load <bank>` instead. The transactions of every file are shown first and a single
    confirmation imports them all.
    """
    from ynab import TransactionClearedStatus

    from ynab_unlinked.activity import log_import
    from ynab_unlinked.core.detect import detect_loaders
    from ynab_unlinked.core.importing import build_import_plan, commit_import_plan, unique_files
    from ynab_unlinked.process import get_or_prompt_account_id
    from ynab_unlinked.utils import display_import_table, display_transaction_table
    from ynab_unlinked.ynab_api.client import Client

    ctx: YnabUnlinkedContext[Any] = context.obj

    files, copies = unique_files(files)
    for copy, first in copies:
        display.warning(f"{copy.name}: same file as {first.name}, imported once")

    with display.process("Finding the bank of each file..."):
        detections = detect_loaders(files, ctx)

    display.console().print(_detection_table(detections, ctx))

    problems = [problem for d in detections if (problem := _problem(d)) is not None]
    problems += [
        f"{d.input_file.name}: {d.best.loader.title} is turned off in the settings"
        for d in detections
        if d.best is not None
        and (saved := ctx.config.entity(d.best.loader.name)) is not None
        and not saved.enabled
    ]
    if problems:
        display.error("Nothing was imported, some files cannot be loaded automatically:")
        display.console().print(display.bullet_list(problems))
        raise typer.Exit(1)

    chosen = [(d.input_file, d.best) for d in detections if d.best is not None]

    if ctx.yes and (
        missing := sorted(
            {c.loader.title for _, c in chosen if ctx.config.entity(c.loader.name) is None}
        )
    ):
        # Checked up front so that --yes never leaves half of the files imported
        display.error(
            f"No saved account for {', '.join(missing)}. Run `yul load <bank>` once without "
            "--yes to select one."
        )
        raise typer.Exit(1)

    if ctx.show:
        for input_file, candidate in chosen:
            display.console().rule(f"{input_file.name}: {candidate.loader.title}")
            display_transaction_table(_parse(input_file, candidate, ctx), ctx.formatter)
        return

    # Every question is asked before anything is written to YNAB, so cancelling imports nothing
    account_ids = [
        get_or_prompt_account_id(
            ctx.config,
            candidate.loader.name,
            force_prompt=ctx.choose_account,
            interactive=not ctx.yes,
        )
        for _, candidate in chosen
    ]

    client = Client(ctx.config.api_key)
    budget_id = ctx.config.budget.id

    plans: list[ImportPlan] = []
    for (input_file, candidate), account_id in zip(chosen, account_ids, strict=True):
        transactions = _parse(input_file, candidate, ctx)
        with display.CliProgress() as progress:
            plans.append(
                build_import_plan(
                    client,
                    budget_id=budget_id,
                    account_id=account_id,
                    entity_name=candidate.loader.name,
                    input_file=input_file,
                    transactions=transactions,
                    buffer_days=ctx.buffer,
                    progress=progress,
                )
            )

    for plan, (input_file, candidate) in zip(plans, chosen, strict=True):
        display.console().rule(f"{input_file.name}: {candidate.loader.title}")
        display_import_table(plan.rows, ctx.formatter)
        display.info(
            f"{len(plan.new_rows)} to import into {_account_name(plan.account_id, ctx)}, "
            f"{plan.already_imported_count} already in YNAB"
        )

    to_import = [plan for plan in plans if plan.new_rows]
    if not to_import:
        display.info("🎉 All done! Nothing to do.")
        return

    count = sum(len(plan.new_rows) for plan in to_import)
    question = (
        f"Create {count} transaction{_plural(count)} from "
        f"{len(to_import)} file{_plural(len(to_import))} in YNAB?"
    )
    if not ctx.yes and not display.confirm(question):
        return

    cleared = (
        TransactionClearedStatus.RECONCILED if ctx.reconcile else TransactionClearedStatus.CLEARED
    )
    created: dict[str, int] = {}
    duplicates: list[str] = []
    for plan, (_, candidate) in zip(plans, chosen, strict=True):
        if not plan.new_rows:
            continue
        with display.CliProgress() as progress:
            result = commit_import_plan(
                client, budget_id=budget_id, plan=plan, cleared=cleared, progress=progress
            )
        log_import(
            ctx.config,
            loader=candidate.loader.name,
            account_id=plan.account_id,
            file=plan.input_file.name,
            created=result.created,
            duplicates=len(result.duplicate_import_ids),
            skipped=plan.already_imported_count,
        )
        created[plan.account_id] = created.get(plan.account_id, 0) + result.created
        duplicates.extend(result.duplicate_import_ids)

    if duplicates:
        display.warning(f"YNAB rejected {len(duplicates)} of them as already imported:")
        display.console().print(display.bullet_list(duplicates))

    total = sum(created.values())
    display.success(f"🎉 All done! {total} transaction{_plural(total)} imported.")
    display.console().print(
        display.bullet_list(
            f"{_account_name(account_id, ctx)}: {amount}" for account_id, amount in created.items()
        )
    )


def _parse(
    input_file: Path, candidate: Candidate, ctx: YnabUnlinkedContext[Any]
) -> list[Transaction]:
    from ynab_unlinked.core.importing import parse_transactions
    from ynab_unlinked.exceptions import ParsingError

    context = dataclasses.replace(ctx, extras=candidate.loader.context_extras(candidate.options))
    try:
        return parse_transactions(candidate.loader.build(candidate.options), input_file, context)
    except ParsingError as e:
        # Detection parsed the file already, so this only happens if it changed meanwhile
        display.error(f"{input_file.name} could not be read: {e.message}")
        raise typer.Exit(1) from e


def _account_name(account_id: str, ctx: YnabUnlinkedContext[Any]) -> str:
    account = ctx.config.account(account_id)
    return account_id if account is None else account.name


def _plural(count: int) -> str:
    return "" if count == 1 else "s"


def _detection_table(detections: list[Detection], ctx: YnabUnlinkedContext[Any]) -> Table:
    from rich import box
    from rich.table import Column, Table
    from rich.text import Text

    table = Table(
        Column("File"),
        Column("Loader"),
        Column("Confidence", justify="right"),
        Column("Transactions", justify="right"),
        Column("Account"),
        title="Files to import",
        box=box.SIMPLE,
    )

    for detection in detections:
        if (best := detection.best) is None:
            table.add_row(
                Text(detection.input_file.name), Text(_status(detection), "red"), "", "", ""
            )
            continue

        table.add_row(
            Text(detection.input_file.name),
            best.loader.title,
            f"{best.confidence:.0%}",
            str(len(best.transactions or ())),
            _account(best, ctx),
        )

    return table


def _account(candidate: Candidate, ctx: YnabUnlinkedContext[Any]) -> str:
    if ctx.choose_account:
        return "asked on import"
    if (entity := ctx.config.entity(candidate.loader.name)) is None:
        return "not set"
    return _account_name(entity.account_id, ctx)


def _status(detection: Detection) -> str:
    from ynab_unlinked.entities.registry import loaders

    if detection.ambiguous:
        return "ambiguous"
    if detection.candidates:
        return "unreadable"
    if any(spec.accepts(detection.input_file) for spec in loaders()):
        return "not recognised"
    return "not supported"


def _problem(detection: Detection) -> str | None:
    from ynab_unlinked.entities.registry import loaders

    name = detection.input_file.name

    if detection.best is not None:
        return None

    if detection.ambiguous:
        options = ", ".join(
            f"{c.loader.key} ({c.confidence:.0%}, {len(c.transactions or ())} transactions)"
            for c in detection.candidates
            if c.transactions is not None
        )
        return f"{name}: more than one bank reads it, use `yul load <bank>`: {options}"

    if detection.candidates:
        errors = "; ".join(f"{c.loader.title}: {c.error}" for c in detection.candidates)
        return f"{name}: could not be read. {errors}"

    if readers := [spec.title for spec in loaders() if spec.accepts(detection.input_file)]:
        return f"{name}: does not look like a statement from {', '.join(readers)}"

    supported = sorted({t.value for spec in loaders() for t in spec.input_types})
    return f"{name}: no bank exports this kind of file. Supported: {', '.join(supported)}"


load.command(name="auto", no_args_is_help=True)(auto)

# Dynamically load all entities commands when present
for _finder, name, ispkg in pkgutil.iter_modules(entities.__path__):
    if not ispkg:
        continue

    module = importlib.import_module(f"{entities.__name__}.{name}")
    if not hasattr(module, "command"):
        continue

    command = module.command

    if callable(command):
        load.command(name=name, no_args_is_help=True)(command)
