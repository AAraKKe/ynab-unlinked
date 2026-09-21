import datetime as dt
from pathlib import Path

import typer
from ynab import TransactionClearedStatus

from ynab_unlinked import display
from ynab_unlinked.config import ConfigV3
from ynab_unlinked.context_object import YnabUnlinkedContext
from ynab_unlinked.display import bullet_list, confirm, console, info, process, question
from ynab_unlinked.entities import Entity
from ynab_unlinked.exceptions import ParsingError
from ynab_unlinked.models import assign_import_ids
from ynab_unlinked.utils import display_import_table, display_transaction_table
from ynab_unlinked.ynab_api.client import Client


def get_or_prompt_account_id(config: ConfigV3, entity_name: str, force_prompt: bool) -> str:
    if entity_name in config.entities and not force_prompt:
        return config.entities[entity_name].account_id

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
    """

    config = context.config
    account_id = get_or_prompt_account_id(
        config, entity.name(), force_prompt=context.choose_account
    )

    try:
        parsed_input = entity.parse(input_file, context)
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

    pending = assign_import_ids(parsed_input)

    client = Client(config.api_key)
    budget_id = config.budget.id
    earliest_transaction = min(t.date for t in parsed_input)

    with process("Reading transactions..."):
        ynab_transactions = client.transactions(
            budget_id=budget_id,
            account_id=account_id,
            since_date=earliest_transaction - dt.timedelta(days=context.buffer),
        )
    display.success("✔ Transactions read")

    known_ids = {t.import_id for t in ynab_transactions if t.import_id is not None}
    already_imported = {
        p.import_id for p in pending if p.import_id in known_ids or p.legacy_import_id in known_ids
    }

    display_import_table(pending, already_imported, context.formatter)

    to_create = [p for p in pending if p.import_id not in already_imported]
    if not to_create:
        info("🎉 All done! Nothing to do.")
        return

    display.info(f"Transactions to import:       {len(to_create)}")

    if not confirm("Do you want to continue and create the transactions?"):
        return

    with process("Creating transactions..."):
        duplicates = client.create_transactions(
            budget_id=budget_id,
            account_id=account_id,
            transactions=to_create,
            cleared=(
                TransactionClearedStatus.RECONCILED
                if context.reconcile
                else TransactionClearedStatus.CLEARED
            ),
        )

    if duplicates:
        display.warning(f"YNAB rejected {len(duplicates)} of them as already imported:")
        console().print(bullet_list(duplicates))

    created = len(to_create) - len(duplicates)
    display.success(f"🎉 All done! {created} transaction{'' if created == 1 else 's'} imported.")
