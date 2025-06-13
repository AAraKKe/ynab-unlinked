from itertools import groupby
from typing import NamedTuple

from rich import box
from rich.prompt import Prompt
from rich.rule import Rule
from rich.style import Style
from rich.table import Column, Table
from ynab.models.account import Account
from ynab.models.transaction_detail import TransactionDetail

from ynab_unlinked.config import get_config
from ynab_unlinked.config.models.v2 import Budget, CurrencyFormat
from ynab_unlinked.display import console, process, question
from ynab_unlinked.models import MatchStatus, Transaction, TransactionWithYnabData
from ynab_unlinked.ynab_api.client import Client

MAX_PAST_TRANSACTIONS_SHOWN = 3


class YnabAmountFormatted(NamedTuple):
    inflow: str
    outflow: str
    amount: str


def format_ynab_amount(ynab_amount: int) -> YnabAmountFormatted:
    value = ynab_amount / 1000
    value_str = f"{value:.2f}€"
    outflow = value_str if ynab_amount < 0 else ""
    inflow = value_str if ynab_amount > 0 else ""

    return YnabAmountFormatted(inflow=inflow, outflow=outflow, amount=value_str)


def prompt_for_api_key() -> str:
    return question("What is the API Key to connect to YNAB?", password=True)


def prompt_for_budget(api_key: str | None = None) -> Budget:
    # If no api_key is provided, try to get it from the config
    if api_key is None:
        if (config := get_config()) is None:
            raise RuntimeError("Could not find config and no API key was provided.")
        api_key = config.api_key

    client = Client(api_key)

    with process("Getting budgets..."):
        budgets = client.budgets()

    console().print("Available budgets:")
    for idx, budget in enumerate(budgets):
        console().print(f" - {idx + 1}. {budget.name}")

    budget_num = Prompt.ask(
        "What budget do you want to use? (By number)",
        choices=[str(i) for i in range(1, len(budgets) + 1)],
        show_choices=False,
        console=console(),
    )
    selected_budget = budgets[int(budget_num) - 1]

    console().print(f"[bold]Selected budget: {selected_budget.name}")

    # Get the full budget to get all the required fields
    budget_details = client.budget(selected_budget.id)

    if budget_details is None:
        raise ValueError(f"Could not find budget with ID {selected_budget.id}")

    if budget_details.currency_format is None:
        raise ValueError(f"Budget {budget_details.name!r} has no currency format")

    if budget_details.date_format is None:
        raise ValueError(f"Budget {budget_details.name!r} has no date format")

    return Budget(
        id=budget_details.id,
        name=budget_details.name,
        date_format=budget_details.date_format.format,
        currency_format=CurrencyFormat(
            iso_code=budget_details.currency_format.iso_code,
            decimal_digits=budget_details.currency_format.decimal_digits,
            decimal_separator=budget_details.currency_format.decimal_separator,
            symbol_first=budget_details.currency_format.symbol_first,
            group_separator=budget_details.currency_format.group_separator,
            currency_symbol=budget_details.currency_format.currency_symbol,
            display_symbol=budget_details.currency_format.display_symbol,
        ),
    )


def display_transaction_table(transactions: list[Transaction]):
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

    console().print(table)


def payee_line(transaction: TransactionWithYnabData) -> str:
    if transaction.ynab_payee is not None and transaction.payee == transaction.ynab_payee:
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


def display_transactions_to_upload(transactions: list[TransactionWithYnabData]):
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

    console().print(Rule("Transactions to be imported"))
    console().print(updload_help_message(partial_matches))
    console().print(table)


def display_partial_matches(transactions: list[TransactionWithYnabData]):
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
        amount = format_ynab_amount(transaction.partial_match.amount)

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
            amount.inflow,
            amount.inflow,
            transaction.partial_match.cleared.name.capitalize(),
            end_section=True,
        )

    console().print(table)


class ReconciliationGroup(NamedTuple):
    account_name: str
    transactions: list[TransactionDetail]


def display_reconciliation_table(
    id_to_account: dict[str, Account], transactions: list[TransactionDetail]
) -> list[ReconciliationGroup]:
    """
    Print a table with the transactions to reconcile per account and return a list
    of transaction groups as displayed in the table.

    The first table is referenced as number one.
    """
    sorted_transactions = sorted(transactions, key=lambda t: t.account_id)

    groups = []
    for counter, (account_id, transaction_group) in enumerate(
        groupby(sorted_transactions, key=lambda t: t.account_id), start=1
    ):
        account = id_to_account[account_id]

        cleared_balance = format_ynab_amount(account.cleared_balance).amount
        uncleared_balance = format_ynab_amount(account.uncleared_balance).amount
        balance = format_ynab_amount(account.balance).amount
        account_name = account.name

        columns = [
            Column(header="Date", justify="left", max_width=10),
            Column(header="Payee", justify="left", width=70),
            Column(header="Inflow", justify="right", max_width=15),
            Column(header="Outflow", justify="right", max_width=15),
            Column(header="Cleared Status", justify="left", width=15),
        ]
        console().print(
            Rule(
                title=(
                    f"[{counter}] "
                    f"{account_name} - [Balance: [green]{balance}[/] = "
                    f"[green]{cleared_balance}[/] (cleraed) + "
                    f"{uncleared_balance} (uncleared)]"
                ),
                align="left",
                style="bold blue",
            )
        )
        table = Table(*columns)

        group = []
        for transaction in transaction_group:
            group.append(transaction)

            amount = format_ynab_amount(transaction.amount)

            table.add_row(
                transaction.var_date.strftime("%m/%d/%Y"),
                transaction.payee_name,
                amount.inflow,
                amount.outflow,
                TransactionWithYnabData.cleared_str(transaction.cleared),
            )

        console().print(table)
        console().print("\n")

        groups.append(ReconciliationGroup(account_name=account_name, transactions=group))
    return groups
