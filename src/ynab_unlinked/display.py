from rich import box, print
from rich.rule import Rule
from rich.style import Style
from rich.table import Column, Table
from rich.prompt import Prompt
from rich.status import Status

from ynab_unlinked.config import Config, ensure_config
from ynab_unlinked.models import MatchStatus, Transaction, TransactionWithYnabData
from ynab_unlinked.ynab_api.client import Client

MAX_PAST_TRANSACTIONS_SHOWN = 3


def prompt_for_api_key() -> str:
    return Prompt.ask("What is the API Key to connect to YNAB?", password=True)


def prompt_for_budget() -> str:
    if ensure_config():
        client = Client(Config.load())
    else:
        api_key = prompt_for_api_key()
        config = Config(api_key=api_key, budget_id="")
        config.save()
        client = Client(config)

    with Status("Getting budgets..."):
        budgets = client.budgets()

    print("Available budgets:")
    for idx, budget in enumerate(budgets):
        print(f" - {idx + 1}. {budget.name}")

    budget_num = Prompt.ask(
        "What budget do you want to use? (By number)",
        choices=[str(i) for i in range(1, len(budgets) + 1)],
        show_choices=False,
    )
    budget = budgets[int(budget_num) - 1]

    print(f"[bold]Selected budget: {budget.name}")
    return budget.id


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
        Column(header="Payee", justify="left", width=70),
        Column(header="Inflow", justify="right", max_width=15),
        Column(header="Outflow", justify="right", max_width=15),
        Column(header="Cleared Status", justify="left", width=15),
    ]
    table = Table(
        *columns,
        title="Recent Transactions",
        caption="Transactions to [cyan bold]update[/] and [bold green]create[/].",
        box=box.SIMPLE,
    )

    for transaction in transactions:
        outflow = transaction.pretty_amount if transaction.amount < 0 else None
        inflow = transaction.pretty_amount if transaction.amount > 0 else None

        if transaction.needs_creation:
            style = "green"
        elif transaction.needs_update:
            if transaction.match_status == MatchStatus.PARTIAL_MATCH:
                style = "yellow"
            else:
                style = "cyan"
        else:
            style = "default"

        if transaction.payee == transaction.ynab_payee:
            payee_line = transaction.ynab_payee
        else:
            payee_line = f"{transaction.ynab_payee} [gray37] [Original payee: {transaction.payee}][/gray37]"

        table.add_row(
            transaction.match_emoji,
            transaction.date.strftime("%m/%d/%Y"),
            payee_line,
            inflow,
            outflow,
            transaction.cleared_status,
            style=style,
        )

    print(Rule("Transactions to be processed"))
    print(
        "The table below shows the transactaions to be loaded into YNAB. The transactions in the input file have been matched with existing transactions in YNAB.\n"
        " - The [green]green[/] rows are new transactions to be created.\n"
        " - The [cyan]blue[/] rows are existing transactions to be updated. These are transactions that have \n"
        "   been matched with an existing transaction in YNAB by date, amount and payee name. \n"
        "   The original payee name is shown in [gray37]gray[/] next to the updated payee name.\n"
        " - The [yellow]yellow[/] rows are existing transactions that have been partially matched with existing\n"
        "   transactions in YNAB. This means that the amount and dates found in the input transaction match those of an existing transaction in YNAB.\n"
        "   However, the payee for the transaction in the input file cannot be easily matched with an existing payee in YNAB.\n"
        "   These transactions need to be validated to ensure that the correct transaction is being updated.\n"
        "The cleared status column shows how the transaction will be loaded to YNAB, not the current status if the transaction was already in YNAB."
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
