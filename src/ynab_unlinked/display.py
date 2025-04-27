from rich.table import Table, Column
from rich import print, box
from rich.style import Style

from ynab_unlinked.models import TransactionWithYnabData, Transaction


MAX_PAST_TRANSACTIONS_SHOWN = 3


def transaction_table(transactions: list[Transaction]):
    columns = [
        Column(header="Date", justify="left", max_width=10),
        Column(header="Payee", justify="left", width=50),
        Column(header="Inflow", justify="right", max_width=15),
        Column(header="Outflow", justify="right", max_width=15),
    ]
    table = Table(
        *columns,
        title="Transactions to process",
        caption=f"Grayed out transactions have already been processed. Only {MAX_PAST_TRANSACTIONS_SHOWN} processed transactions are shown.",
        box=box.SIMPLE,
    )

    past_counter = 0
    for transaction in transactions:
        style = Style(color="gray37" if transaction.past else "default")

        past_counter += int(transaction.past)
        if past_counter == MAX_PAST_TRANSACTIONS_SHOWN:
            # Stop adding transactions that are past after 5 for clarification
            table.add_row("...", "...", "...", "...")
            break

        outflow = transaction.pretty_amount if transaction.amount < 0 else None
        inflow = transaction.pretty_amount if transaction.amount > 0 else None

        table.add_row(
            transaction.date.strftime("%m/%d/%Y"),
            transaction.payee,
            inflow,
            outflow,
            style=style,
        )

    print(table)


def transactions_to_upload(transactions: list[TransactionWithYnabData]):
    columns = [
        Column(header="Match", justify="center", width=5),
        Column(header="Date", justify="left", max_width=10),
        Column(header="Payee", justify="left", width=50),
        Column(header="Inflow", justify="right", max_width=15),
        Column(header="Outflow", justify="right", max_width=15),
        Column(header="Cleared Status", justify="left", width=15),
    ]
    table = Table(
        *columns,
        title="Transactions to crate/update",
        caption="Final set of transactions to be added to YNAB. [blue bold]To update[/] and [bold green]create.",
    )

    for transaction in transactions:
        outflow = transaction.pretty_amount if transaction.amount < 0 else None
        inflow = transaction.pretty_amount if transaction.amount > 0 else None

        table.add_row(
            "🔗" if transaction.needs_update else "",
            transaction.date.strftime("%m/%d/%Y"),
            transaction.ynab_payee,
            inflow,
            outflow,
            transaction.cleared_status,
            style=(
                "bold green"
                if transaction.needs_creation
                else "bold blue" if transaction.needs_update else "default"
            ),
        )

    print(table)
