import datetime as dt
from typing import Annotated, Literal

from rich import print
from rich.prompt import Confirm, Prompt
from rich.status import Status
from typer import Context, Option
from ynab.models.transaction_cleared_status import TransactionClearedStatus

from ynab_unlinked import app, display
from ynab_unlinked.config import TRANSACTION_GRACE_PERIOD_DAYS
from ynab_unlinked.context_object import YnabUnlinkedContext
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
    config = ctx.config
    budget_id = config.budget_id

    last_reconciliation_date = None if all else config.last_reconciliation_date

    client = Client(api_key=config.api_key)

    cleared_allowed = {TransactionClearedStatus.CLEARED}
    if uncleared:
        cleared_allowed.add(TransactionClearedStatus.UNCLEARED)

    with Status("Getting transactions from YNAB"):
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
        print("[bold gree]All accounts are already reconciled!")
        return

    reconcile_groups = display.reconciliation_table(
        ids_to_account, transactions_to_reconcile
    )

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
        print("No accounts to reconcile.\n👋 Bye!")
        return

    print("\nThe following accounts will be reconciled:")
    for acc in selected_accounts:
        print(f"- {acc}")

    if not Confirm.ask("\nShould I go ahead and reconcile them?"):
        print("Alright, cancelling reconciliation.\n👋 Bye!")
        return

    for transaction in selected_transactions:
        transaction.cleared = TransactionClearedStatus.RECONCILED

    with Status("Updating transactions"):
        client.update_transactions(
            budget_id=budget_id, transactions=selected_transactions
        )

    latest_date = max(t.var_date for t in selected_transactions)
    ctx.config.last_reconciliation_date = latest_date - dt.timedelta(
        days=TRANSACTION_GRACE_PERIOD_DAYS
    )
    ctx.config.save()

    print("[bold green]🎉 Reconciliation done!")
