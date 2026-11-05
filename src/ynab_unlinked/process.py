from pathlib import Path

import typer
from ynab import TransactionClearedStatus

from ynab_unlinked import display
from ynab_unlinked.activity import log_import
from ynab_unlinked.config import LatestConfig
from ynab_unlinked.context_object import YnabUnlinkedContext
from ynab_unlinked.core.importing import build_import_plan, commit_import_plan, parse_transactions
from ynab_unlinked.display import CliProgress, bullet_list, confirm, console, info, question
from ynab_unlinked.entities import Entity
from ynab_unlinked.exceptions import ParsingError
from ynab_unlinked.utils import display_import_table, display_transaction_table
from ynab_unlinked.ynab_api.client import Client


def get_or_prompt_account_id(
    config: LatestConfig, entity_name: str, force_prompt: bool, interactive: bool = True
) -> str:
    if (loader := config.entity(entity_name)) is not None and not force_prompt:
        return loader.account_id

    if not interactive:
        display.error(
            f"No saved account for {entity_name}. Run this load once without --yes to select one."
        )
        raise typer.Exit(1)

    display.info(f"Lets select the account for {entity_name.capitalize()}:")
    client = Client(config.api_key)
    budget_id = config.budget.id

    accounts = [acc for acc in client.accounts(budget_id=budget_id) if not acc.closed]

    console().print(bullet_list(f"{idx + 1:>2}: {acc.name}" for idx, acc in enumerate(accounts)))

    acc_num = question(
        "What account are the transactions going to be imported to? (By number)",
        choices=[str(i) for i in range(1, len(accounts) + 1)],
        show_choices=False,
    )
    account = accounts[int(acc_num) - 1]

    info(f"Account selected: {account.name}")

    account_id = str(account.id)
    if not force_prompt:
        config.set_entity_account(entity_name, account_id)
        config.save()

    return account_id


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
    account_id = get_or_prompt_account_id(
        config, entity.name(), force_prompt=context.choose_account, interactive=not context.yes
    )

    try:
        parsed_input = parse_transactions(entity, input_file, context)
    except ParsingError as e:
        display.error(f"Error when parsing {e.input_file}")
        display.console().print(f"  Message: {e.message}")
        raise typer.Exit(1) from e

    if context.show:
        display_transaction_table(parsed_input, context.formatter)
        return

    if not parsed_input:
        info("🎉 All done! Nothing to do.")
        return

    client = Client(config.api_key)
    budget_id = config.budget.id

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
        )

    display_import_table(plan.rows, context.formatter)

    if not plan.new_rows:
        info("🎉 All done! Nothing to do.")
        return

    display.info(f"Transactions to import:       {len(plan.new_rows)}")

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
    )

    created = result.created
    display.success(f"🎉 All done! {created} transaction{'' if created == 1 else 's'} imported.")
