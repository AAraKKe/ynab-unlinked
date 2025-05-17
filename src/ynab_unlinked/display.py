from rich import box, print
from rich.prompt import Prompt
from rich.rule import Rule
from rich.status import Status
from rich.style import Style
from rich.table import Column, Table

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
        caption=f"Only {MAX_PAST_TRANSACTIONS_SHOWN} processed transactions are shown.",
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


def payee_line(transaction: TransactionWithYnabData) -> str:
    if (
        transaction.ynab_payee is not None
        and transaction.payee == transaction.ynab_payee
    ):
        return transaction.ynab_payee

    return f"{transaction.ynab_payee} [gray37] [Original payee: {transaction.payee}][/gray37]"


def updload_help_message(with_partial_matches=False) -> str:
    main_message = (
        "The table below shows the transactaions to be imported to YNAB. The transactions in the input file "
        "have been matched with existing transactions in YNAB.\n"
        " - The [green]green[/] rows are new transactions to be imported.\n"
    )
    if with_partial_matches:
        main_message += (
            " - The [yellow]yellow[/] rows are transaction to be imported that match in date and amount with\n"
            "   transations that exist in YNAB but for which teh payee name could not be matched.\n"
            "   This is usually because the name from the import file is substantially different any payee "
            "present in YNAB.\n"
            "   If you accept these transactions are valid, we will keep track of this naming for future imports."
        )

    main_message += (
        "The cleared status column shows how the transaction will be loaded to YNAB, not the current "
        "status if the transaction was already in YNAB."
    )

    return main_message


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

    partial_matches = False
    for transaction in transactions:
        outflow = transaction.pretty_amount if transaction.amount < 0 else None
        inflow = transaction.pretty_amount if transaction.amount > 0 else None

        if transaction.needs_creation:
            if transaction.match_status == MatchStatus.PARTIAL_MATCH:
                style = "yellow"
                partial_matches = True
            else:
                style = "green"
        else:
            style = "default"

        table.add_row(
            transaction.match_emoji,
            transaction.date.strftime("%m/%d/%Y"),
            payee_line(transaction),
            inflow,
            outflow,
            transaction.cleared_status,
            style=style,
        )

    print(Rule("Transactions to be imported"))
    print(updload_help_message(partial_matches))
    print(table)


def partial_matches(transactions: list[TransactionWithYnabData]):
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
        caption=(
            "Each pair of transactions shows the imported transaction (top) \n"
            "and the partial match in YNAB (bottom)."
        ),
        box=box.SIMPLE,
        row_styles=["", "gray70"],
    )

    for transaction in transactions:
        # If we do not need to import it, skip it
        if not transaction.needs_creation:
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
