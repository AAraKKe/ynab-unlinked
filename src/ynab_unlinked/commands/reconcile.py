import datetime as dt
from typing import Annotated

from typer import Context, Option
from ynab import Account, TransactionClearedStatus, TransactionDetail

from ynab_unlinked import app, display
from ynab_unlinked.choices import Choice
from ynab_unlinked.commands.apps.reconcile import Reconcile
from ynab_unlinked.config import ConfigV2
from ynab_unlinked.config.constants import TRANSACTION_GRACE_PERIOD_DAYS
from ynab_unlinked.context_object import YnabUnlinkedContext
from ynab_unlinked.display import process
from ynab_unlinked.ynab_api import Client


def build_choices(transactions: list[TransactionDetail], accounts: list[Account]) -> list[Choice]:
    accounts_by_id = {acc.id: acc for acc in accounts}
    choices_per_account: dict[str, list[Choice | str]] = {}

    for transaction in transactions:
        choice = Choice(id=f"transaction-{transaction.id}", transaction=transaction)
        forced_selection = (
            False if transaction.cleared is TransactionClearedStatus.UNCLEARED else None
        )
        choice.enable_forced_selected(forced_selection)
        choices_per_account.setdefault(transaction.account_id, []).append(choice)

    return [
        Choice(
            id=f"account-{acc_id}",
            title=account.name,
            choices=choices_per_account.get(acc_id),
            account=account,
        )
        for acc_id, account in accounts_by_id.items()
        if choices_per_account.get(acc_id)
    ]


@app.command()
def reconcile(
    context: Context,
    all: Annotated[
        bool,
        Option(
            "--all",
            "-a",
            help=(
                "Include all transactions, not just those since the last reconciliation. "
                "Use this if some transactions were cleared with a significant delay. "
                "Note: This may take longer to run. "
                "Alternatively, use the --buffer option to include more days before the last reconciliation."
            ),
        ),
    ] = False,
    buffer: Annotated[
        int,
        Option(
            "-b",
            "--buffer",
            help=(
                "Number of days before the last reconciliation to include when checking transactions. "
                "This helps catch any late-cleared transactions."
            ),
            show_default=True,
        ),
    ] = 7,
):
    """Help reconciling your accounts in one go"""

    ctx: YnabUnlinkedContext = context.obj
    config: ConfigV2 = ctx.config

    budget_id = config.budget.id

    last_reconciliation_date = None if all else config.last_reconciliation_date

    if last_reconciliation_date:
        last_reconciliation_date -= dt.timedelta(days=buffer)

    client = Client(api_key=config.api_key)

    with process("Getting transactions from YNAB"):
        transactions_to_reconcile = [
            transaction
            for transaction in client.transactions(
                budget_id=budget_id, since_date=last_reconciliation_date
            )
            if transaction.cleared is not TransactionClearedStatus.RECONCILED
        ]
        accounts = client.accounts(budget_id=budget_id)

    if not transactions_to_reconcile:
        display.success("All accounts are already reconciled!")
        return

    choices = build_choices(transactions_to_reconcile, accounts)
    return_value = Reconcile(config, choices, formatter=ctx.formatter).run()

    if return_value == 2:
        display.info("Nothing to reconcile.\n👋 Bye!")
        return

    if return_value == 1:
        display.info("👋 Bye!")
        return

    selected_transactions = [
        child.transaction
        for choice in choices
        for child in choice.choices
        if child.transaction and child.is_selected
    ]

    for transaction in selected_transactions:
        transaction.cleared = TransactionClearedStatus.RECONCILED

    with process("Updating transactions"):
        client.update_transactions(budget_id=budget_id, transactions=selected_transactions)

    latest_date = max(t.var_date for t in selected_transactions)
    config.last_reconciliation_date = latest_date - dt.timedelta(days=TRANSACTION_GRACE_PERIOD_DAYS)
    config.save()

    display.success("🎉 Reconciliation done!")
