from collections.abc import Sequence
from pathlib import Path

import typer
from rich.markup import escape
from ynab import Account, TransactionClearedStatus

from ynab_unlinked.activity import log_import
from ynab_unlinked.cli import display
from ynab_unlinked.cli.context_object import YnabUnlinkedContext
from ynab_unlinked.cli.display import CliProgress, bullet_list, confirm, console, info, question
from ynab_unlinked.cli.utils import display_import_table, display_transaction_table
from ynab_unlinked.config import ImportedFiles, LatestConfig, update_config
from ynab_unlinked.core.accounts import AccountState, account_state
from ynab_unlinked.core.imported_files import Original, remove_originals, shown
from ynab_unlinked.core.importing import (
    ImportPlan,
    RowStatus,
    build_import_plan,
    commit_import_plan,
)
from ynab_unlinked.entities import Entity
from ynab_unlinked.entities.registry import loaders
from ynab_unlinked.exceptions import ParsingError
from ynab_unlinked.formatter import Formatter
from ynab_unlinked.store import Store, store_path
from ynab_unlinked.text import name_list, plural
from ynab_unlinked.ynab_api.client import Client


def get_or_prompt_account_id(
    config: LatestConfig,
    entity_name: str,
    force_prompt: bool,
    interactive: bool = True,
    accounts: Sequence[Account] | None = None,
) -> str:
    """The account the statements of `entity_name` go to: the saved one while it is open,
    else the one the user picks (saved for next time unless `force_prompt`).

    `accounts` are the budget's accounts when the caller has them already; they are read from
    YNAB otherwise. A saved account that was closed or deleted in YNAB is asked for again,
    since YNAB takes transactions into a closed account and then shows them nowhere.
    """
    loader = config.entity(entity_name)
    if (loader is None or force_prompt) and not interactive:
        display.error(
            f"No saved account for {_bank_title(entity_name)}. "
            "Run this load once without --yes to select one."
        )
        raise typer.Exit(1)

    if accounts is None:
        accounts = Client(config.api_key).accounts(budget_id=config.budget.id)

    if loader is not None and not force_prompt:
        state = account_state(loader.account_id, accounts)
        if state is AccountState.OPEN:
            return loader.account_id
        gone = f"The account saved for {_bank_title(entity_name)} {state.reason}."
        if not interactive:
            display.error(f"{gone} Run without --yes to pick another one.")
            raise typer.Exit(1)
        display.warning(gone)

    display.info(f"Lets select the account for {_bank_title(entity_name)}:")
    choices = [acc for acc in accounts if not acc.closed and not acc.deleted]

    console().print(bullet_list(f"{idx + 1:>2}: {acc.name}" for idx, acc in enumerate(choices)))

    acc_num = question(
        "What account are the transactions going to be imported to? (By number)",
        choices=[str(i) for i in range(1, len(choices) + 1)],
        show_choices=False,
    )
    account = choices[int(acc_num) - 1]

    info(f"Account selected: {account.name}")

    account_id = str(account.id)
    if not force_prompt:
        # Saved on the file as it is now, so settings the app saved meanwhile are kept
        config.set_entity_account(entity_name, account_id)
        update_config(lambda saved: saved.set_entity_account(entity_name, account_id))

    return account_id


def _bank_title(entity_name: str) -> str:
    return next((spec.title for spec in loaders() if spec.name == entity_name), entity_name)


def open_store(yes: bool) -> Store | None:
    """The budget copy, where the rows left out of imports and the matches YNAB hides are.

    A store that cannot be opened only warns, like the activity log, since the table is
    shown before anything is sent. With `--yes` nobody looks at it, so it stops the command
    instead of sending rows the user asked never to send.
    """
    try:
        return Store(store_path())
    except Exception as error:
        message = f"Could not open the rows left out of imports on this computer: {error}"
        if yes:
            display.error(message)
            raise typer.Exit(1) from error
        display.warning(f"{message}. Every row is shown as if none was left out.")
        return None


def plan_notes(plan: ImportPlan, formatter: Formatter) -> None:
    """Name the rows held back because they may be in YNAB (`RowStatus.MAYBE_IN_YNAB`)."""
    if not (held := plan.with_status(RowStatus.MAYBE_IN_YNAB)):
        return
    display.warning(
        f"{plural(len(held), 'row')} may already be in YNAB and "
        f"{'is' if len(held) == 1 else 'are'} not sent. Import or leave "
        f"{'it' if len(held) == 1 else 'them'} out in `yul app`:"
    )
    console().print(
        bullet_list(
            # Bank and YNAB text, never markup
            escape(
                f"{formatter.format_date(row.transaction.date)} {row.transaction.payee} "
                f"{formatter.format_amount(row.transaction.amount)}: same amount as "
                f"{row.twin.payee or 'a transaction'} on {formatter.format_date(row.twin.date)}"
            )
            for row in held
            if row.twin is not None
        )
    )


REMOVE_CHOICES = ("yes", "no", "always", "never")
"""The answers to "Remove the imported files?": the last two save it as the setting."""


def originals(paths: Sequence[Path]) -> list[Original]:
    """The files as they are now, before they are read: one that changes during the import is
    not removed after it. A path that cannot be read as a file is not offered for removal."""
    found: list[Original] = []
    for path in dict.fromkeys(paths):
        try:
            found.append(Original.of(path))
        except OSError:
            continue
    return found


def offer_removal(config: LatestConfig, files: Sequence[Original], *, interactive: bool) -> None:
    """Remove the files an import read, as the setting `imported_files` says.

    `ASK` asks once for all of them, where "always" and "never" save the answer so that the
    question is not asked again; without a terminal to ask on (`--yes`) the files stay.
    Removing deletes a file for good, and leaves alone one that changed since it was read.
    """
    mode = config.imported_files
    if mode is ImportedFiles.KEEP or not files:
        return
    if mode is ImportedFiles.ASK:
        if not interactive:
            return
        names = name_list([original.path.name for original in files])
        info(
            f"{'It is' if len(files) == 1 else 'They are'} in YNAB now. Removing deletes "
            f"{'it' if len(files) == 1 else 'them'} for good, not to the Trash. "
            "`always` and `never` save the answer (`yul config set imported_files` changes it)."
        )
        try:
            answer = question(
                # A file name is the user's text, never markup
                escape(f"Remove {names} from this computer?"),
                choices=list(REMOVE_CHOICES),
                default="no",
            )
        except EOFError:
            # Nobody to answer: the files stay
            return
        if answer in ("always", "never"):
            choice = ImportedFiles.REMOVE if answer == "always" else ImportedFiles.KEEP
            config.imported_files = choice
            update_config(lambda saved: setattr(saved, "imported_files", choice))
        if answer not in ("yes", "always"):
            return

    removal = remove_originals(files)
    if removal.removed:
        display.success(escape(f"Removed {name_list([shown(path) for path in removal.removed])}"))
    for path, why in removal.failed:
        display.warning(escape(f"Could not remove {shown(path)}: {why}"))


def process_transactions(
    entity: Entity,
    input_file: Path,
    context: YnabUnlinkedContext,
) -> None:
    """
    Process the transactions from the input file and import them into YNAB.

    If the Entity calling this method does not have a config stored, the user will be prompted to select an account
    this entity should publish transactions to. This account will be used moving forward when using this entity.

    If the user called `yul -a` the user will always be promptped to select
    and account and the selected account won't be saved for this particular entity.

    With `yul load --yes` nothing is asked: the import goes ahead without confirmation and an entity
    with no saved account is an error.
    """

    config = context.config

    try:
        parsed_input = entity.parse(input_file)
    except ParsingError as e:
        display.error(f"Error when parsing {e.input_file}")
        display.console().print(f"  Message: {escape(e.message)}")
        raise typer.Exit(1) from e

    # Showing reads nothing from YNAB: no account is asked for, or saved
    if context.show:
        display_transaction_table(parsed_input, context.formatter)
        return

    read = originals([input_file])

    account_id = get_or_prompt_account_id(
        config, entity.name(), force_prompt=context.choose_account, interactive=not context.yes
    )

    if not parsed_input:
        info("🎉 All done! Nothing to do.")
        return

    client = Client(config.api_key)
    budget_id = config.budget.id

    store = open_store(context.yes)
    with CliProgress() as progress:
        plan = build_import_plan(
            client,
            budget_id=budget_id,
            account_id=account_id,
            entity_name=entity.name(),
            input_file=input_file,
            transactions=parsed_input,
            buffer_days=context.buffer,
            progress=progress,
            store=store,
        )

    display_import_table(plan.rows, context.formatter)
    plan_notes(plan, context.formatter)

    if not plan.new_rows:
        info("🎉 All done! Nothing to do.")
        offer_removal(config, read, interactive=not context.yes)
        return

    display.info(f"Transactions to import:       {len(plan.new_rows)}")
    if left_out := len(plan.with_status(RowStatus.EXCLUDED)):
        display.info(f"Left out:                     {left_out}")
    if held := len(plan.with_status(RowStatus.MAYBE_IN_YNAB)):
        display.info(f"May be in YNAB, not sent:     {held}")

    if not context.yes and not confirm("Do you want to continue and create the transactions?"):
        return

    with CliProgress() as progress:
        result = commit_import_plan(
            client,
            budget_id=budget_id,
            plan=plan,
            cleared=(
                TransactionClearedStatus.RECONCILED
                if context.reconcile
                else TransactionClearedStatus.CLEARED
            ),
            progress=progress,
            store=store,
        )

    if result.duplicate_import_ids:
        display.warning(
            f"YNAB rejected {len(result.duplicate_import_ids)} of them as already imported:"
        )
        console().print(bullet_list(result.duplicate_import_ids))

    log_import(
        config,
        loader=entity.name(),
        account_id=account_id,
        file=input_file.name,
        created=result.created,
        duplicates=len(result.duplicate_import_ids),
        skipped=plan.already_imported_count,
        matched=len(plan.with_status(RowStatus.MATCHED)),
        excluded=left_out,
        held=held,
    )

    created = result.created
    display.success(f"🎉 All done! {created} transaction{'' if created == 1 else 's'} imported.")
    offer_removal(config, read, interactive=not context.yes)
