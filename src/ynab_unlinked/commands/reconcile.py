import datetime as dt
from typing import Annotated, Literal

from rich.prompt import Prompt
from typer import Context, Option
from ynab.models.transaction_cleared_status import TransactionClearedStatus

from ynab_unlinked import app, display
from ynab_unlinked.config import ConfigV2
from ynab_unlinked.config.constants import TRANSACTION_GRACE_PERIOD_DAYS
from ynab_unlinked.context_object import YnabUnlinkedContext
from ynab_unlinked.display import confirm, process
from ynab_unlinked.utils import display_reconciliation_table
from ynab_unlinked.ynab_api import Client


def indexes_to_reconcile(max: int) -> list[int] | Literal["all"]:
    selection = Prompt.ask(
        (
            "Select which accounts you want to reconcile from the list above. You can suply several "
            "of them with a comma separated list of numbers (e.g. 1,2,4) or answer 'all' to reconcile all acounts."
        ),
        default="all",
    )

    if selection == "all":
        return "all"

    while True:
        try:
            if selection == ".q":
                return []

            indexes = [int(i.strip()) for i in selection.split(",")]

            if any(i > max for i in indexes):
                raise RuntimeError()

            return indexes
        except Exception:
            selection = Prompt.ask(
                (
                    "Select either a set of numbers (e.g. 1,2,4) or 'all' to reoncile all accounts.\n"
                    "If you want to quit, answer '.q'"
                ),
                default="all",
            )


@app.command()
def reconcile(
    context: Context,
    all: Annotated[
        bool,
        Option(
            "--all",
            "-a",
            is_flag=True,
            help=(
                "Get all transactions. By default, only transactions created after the last "
                "time this command was run will be considered."
            ),
        ),
    ] = False,
    uncleared: Annotated[
        bool,
        Option(
            "--uncleared",
            "-u",
            is_flag=True,
            help="Reconcile even uncleared transactions",
        ),
    ] = False,
):
    """Help reconciling your accounts in one go"""

    ctx: YnabUnlinkedContext = context.obj
    config: ConfigV2 = ctx.config
    budget_id = config.budget.id

    last_reconciliation_date = None if all else config.last_reconciliation_date

    client = Client(api_key=config.api_key)

    cleared_allowed = {TransactionClearedStatus.CLEARED}
    if uncleared:
        cleared_allowed.add(TransactionClearedStatus.UNCLEARED)

    with process("Getting transactions from YNAB"):
        transactions_to_reconcile = [
            transaction
            for transaction in client.transactions(
                budget_id=budget_id, since_date=last_reconciliation_date
            )
            if transaction.cleared in cleared_allowed
        ]
        accounts = client.accounts(budget_id=budget_id)
        ids_to_account = {acc.id: acc for acc in accounts}

    if not transactions_to_reconcile:
        display.success("All accounts are already reconciled!")
        return

    reconcile_groups = display_reconciliation_table(ids_to_account, transactions_to_reconcile)

    selection = indexes_to_reconcile(max=len(reconcile_groups))

    if selection == "all":
        selected_transactions = transactions_to_reconcile
        selected_ids = {t.account_id for t in selected_transactions}
        selected_accounts = [ids_to_account[acc_id].name for acc_id in selected_ids]
    else:
        selected_transactions = []
        selected_accounts = []
        for index in selection:
            selected_accounts.append(reconcile_groups[index - 1].account_name)
            selected_transactions.extend(reconcile_groups[index - 1].transactions)

    if not selected_transactions:
        display.info("No accounts to reconcile.\n👋 Bye!")
        return

    display.info("\nThe following accounts will be reconciled:")
    for acc in selected_accounts:
        display.console().print(f"- {acc}")

    if not confirm("\nShould I go ahead and reconcile them?"):
        display.info("Alright, cancelling reconciliation.\n👋 Bye!")
        return

    for transaction in selected_transactions:
        transaction.cleared = TransactionClearedStatus.RECONCILED

    with process("Updating transactions"):
        client.update_transactions(budget_id=budget_id, transactions=selected_transactions)

    latest_date = max(t.var_date for t in selected_transactions)
    config.last_reconciliation_date = latest_date - dt.timedelta(days=TRANSACTION_GRACE_PERIOD_DAYS)
    config.save()

    display.success("🎉 Reconciliation done!")
