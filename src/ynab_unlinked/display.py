from rich import box, print
from rich.style import Style
from rich.table import Column, Table

from ynab_unlinked.models import MatchStatus, Transaction, TransactionWithYnabData

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
        title="Recent Transactions",
        caption="Transactions to [blue bold]update[/] and [bold green]create[/]. Only most recent transactions are shown.",
        box=box.SIMPLE,
    )

    for transaction in transactions:
        outflow = transaction.pretty_amount if transaction.amount < 0 else None
        inflow = transaction.pretty_amount if transaction.amount > 0 else None

        if transaction.needs_creation:
            style = "bold green"
        elif transaction.needs_update:
            if transaction.match_status == MatchStatus.PARTIAL_MATCH:
                style = "bold yellow"
            else:
                style = "bold blue"
        else:
            style = "default"

        table.add_row(
            transaction.match_emoji,
            transaction.date.strftime("%m/%d/%Y"),
            transaction.ynab_payee,
            inflow,
            outflow,
            transaction.ynab_cleared_status,
            style=style,
        )

    print(table)


def partial_matches(transactions: list[TransactionWithYnabData]):
    print(
        "\n[bold yellow]🚨 Some transactions have been partially matched and require an update![/]"
        "\n\n"
        "This means that the amount and dates found in the input transaction match those of an existing transaction in YNAB."
        " However, the payee for the transaction in the input file cannot be easily matched with an existing payee in YNAB."
        "\n"
        "This is common if payees in your entity export and in YNAB are not very similar. \n"
    )

    columns = [
        Column(header="Date", justify="left", max_width=10),
        Column(header="Payee", justify="left", width=50),
        Column(header="Inflow", justify="right", max_width=15),
        Column(header="Outflow", justify="right", max_width=15),
        Column(header="Cleared Status", justify="left", width=15),
    ]
    table = Table(
        *columns,
        title="Partial Matches",
        caption="Each pair of transactions shows the imported transaction (top) and the \npartial match in YNAB (bottom).",
        box=box.SIMPLE,
        row_styles=["", "gray70"],
    )

    for transaction in transactions:
        # If we do not need to update it, skip it
        if not transaction.needs_update:
            continue

        # Skip if no partial match
        if (
            transaction.match_status != MatchStatus.PARTIAL_MATCH
            or transaction.partial_match is None
        ):
            continue

        # Original transaction row
        orig_outflow = transaction.pretty_amount if transaction.amount < 0 else None
        orig_inflow = transaction.pretty_amount if transaction.amount > 0 else None

        # YNAB transaction row (from partial_match)
        ynab_amount = transaction.partial_match.amount / 1000
        ynab_pretty_amount = f"{ynab_amount:.2f}€"
        ynab_outflow = ynab_pretty_amount if ynab_amount < 0 else None
        ynab_inflow = ynab_pretty_amount if ynab_amount > 0 else None

        # Add the pair of rows
        table.add_row(
            transaction.date.strftime("%m/%d/%Y"),
            transaction.payee,
            orig_inflow,
            orig_outflow,
            "",
        )

        table.add_row(
            transaction.partial_match.var_date.strftime("%m/%d/%Y"),
            transaction.partial_match.payee_name or "",
            ynab_inflow,
            ynab_outflow,
            transaction.partial_match.cleared.name.capitalize(),
            end_section=True,
        )

    print(table)
