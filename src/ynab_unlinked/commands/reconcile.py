import datetime as dt
from typing import Annotated

from typer import Context, Option
from ynab import Account, TransactionClearedStatus, TransactionDetail

from ynab_unlinked import app, display
from ynab_unlinked.activity import log_reconcile
from ynab_unlinked.choices import Choice
from ynab_unlinked.commands.apps.reconcile import Reconcile
from ynab_unlinked.config import LatestConfig, update_config
from ynab_unlinked.core.reconcile import next_reconciliation_date, reconciliation_overview
from ynab_unlinked.core.reconcile import reconcile as reconcile_transactions
from ynab_unlinked.display import CliProgress
from ynab_unlinked.setup import ensure_config
from ynab_unlinked.ynab_api import Client


def build_choices(transactions: list[TransactionDetail], accounts: list[Account]) -> list[Choice]:
    accounts_by_id = {str(acc.id): acc for acc in accounts}
    choices_per_account: dict[str, list[Choice | str]] = {}

    for transaction in transactions:
        choice = Choice(id=f"transaction-{transaction.id}", transaction=transaction)
        forced_selection = (
            False if transaction.cleared is TransactionClearedStatus.UNCLEARED else None
        )
        choice.enable_forced_selected(forced_selection)
        choices_per_account.setdefault(str(transaction.account_id), []).append(choice)

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

    ctx = ensure_config(context)
    config: LatestConfig = ctx.config

    budget_id = config.budget.id

    last_reconciliation_date = None if all else config.last_reconciliation_date

    if last_reconciliation_date:
        last_reconciliation_date -= dt.timedelta(days=buffer)

    client = Client(api_key=config.api_key)

    with CliProgress() as progress:
        overview = reconciliation_overview(
            client, budget_id=budget_id, since=last_reconciliation_date, progress=progress
        )

    if not overview:
        display.success("All accounts are already reconciled!")
        return

    choices = build_choices(
        [t for group in overview for t in group.transactions],
        [group.account for group in overview],
    )
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
    selected_ids = {transaction.id for transaction in selected_transactions}
    left_unreconciled = [
        transaction.var_date
        for group in overview
        for transaction in group.transactions
        if transaction.id not in selected_ids
    ]

    with CliProgress() as progress:
        latest_date = reconcile_transactions(
            client, budget_id=budget_id, transactions=selected_transactions, progress=progress
        )

    if latest_date is None:
        display.info("Nothing to reconcile.\n👋 Bye!")
        return

    next_date = next_reconciliation_date(
        [t.var_date for t in selected_transactions], left_unreconciled
    )
    config.last_reconciliation_date = next_date
    # The TUI may have been open for minutes: save on the file as it is now, so settings the
    # app saved meanwhile are kept
    update_config(lambda saved: setattr(saved, "last_reconciliation_date", next_date))

    log_reconcile(
        config,
        [
            (str(group.account.id), group.account.name, locked)
            for group in overview
            if (locked := sum(t.id in selected_ids for t in group.transactions))
        ],
    )

    display.success("🎉 Reconciliation done!")
