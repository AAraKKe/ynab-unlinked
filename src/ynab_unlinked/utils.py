from collections.abc import Sequence
from pathlib import Path

from rich import box
from rich.prompt import Prompt
from rich.rule import Rule
from rich.style import Style
from rich.table import Column, Table

from ynab_unlinked.config import get_config
from ynab_unlinked.config.models.v2 import Budget, CurrencyFormat
from ynab_unlinked.display import console, process, question
from ynab_unlinked.entities import InputType
from ynab_unlinked.formatter import Formatter
from ynab_unlinked.models import MatchStatus, Transaction, TransactionWithYnabData
from ynab_unlinked.ynab_api.client import Client

MAX_PAST_TRANSACTIONS_SHOWN = 3


def prompt_for_api_key() -> str:
    return question("What is the API Key to connect to YNAB?", password=True)


def extract_type(input_file: Path, valid: Sequence[InputType] | None = None) -> InputType:
    extension = input_file.suffix[1:]

    if extension not in InputType:
        raise LookupError(f"Extension {extension!r} is not supported. File: {input_file}")

    valid_extensions = {v.value for v in valid} if valid else [v.value for v in InputType]
    if extension not in valid_extensions:
        raise AttributeError(
            f"Input file {input_file} does not have a supported extension. Supported: {valid_extensions}"
        )

    return InputType(extension)


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
    console().print(f" - {idx + 1}. {budget.name}" for idx, budget in enumerate(budgets))

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


def display_transaction_table(transactions: list[Transaction], formatter: Formatter):
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

        amount_str = formatter.format_amount(transaction.amount)
        outflow = amount_str if transaction.amount < 0 else ""
        inflow = amount_str if transaction.amount > 0 else ""

        table.add_row(
            formatter.format_date(transaction.date),
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


def display_transactions_to_upload(
    transactions: list[TransactionWithYnabData], formatter: Formatter
):
    if not transactions:
        return

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
        amount_str = formatter.format_amount(transaction.amount)
        outflow = amount_str if transaction.amount < 0 else ""
        inflow = amount_str if transaction.amount > 0 else ""

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
            formatter.format_date(transaction.date),
            payee_line(transaction),
            inflow,
            outflow,
            transaction.cleared_status,
            style=style,
        )

    console().print(Rule("Transactions to be imported"))
    console().print(updload_help_message(partial_matches))
    console().print(table)


def display_partial_matches(transactions: list[TransactionWithYnabData], formatter: Formatter):
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
        orig_amount_str = formatter.format_amount(transaction.amount)
        orig_outflow = orig_amount_str if transaction.amount < 0 else ""
        orig_inflow = orig_amount_str if transaction.amount > 0 else ""

        # YNAB transaction row (from partial_match)
        ynab_amount_str = formatter.format_amount_milli(transaction.partial_match.amount)
        ynab_outflow = ynab_amount_str if transaction.partial_match.amount < 0 else ""
        ynab_inflow = ynab_amount_str if transaction.partial_match.amount > 0 else ""

        # Add the pair of rows
        table.add_row(
            formatter.format_date(transaction.date),
            transaction.payee,
            orig_inflow,
            orig_outflow,
            transaction.cleared_status,
        )

        table.add_row(
            formatter.format_date(transaction.partial_match.var_date),
            transaction.partial_match.payee_name or "",
            ynab_inflow,
            ynab_outflow,
            transaction.partial_match.cleared.name.capitalize(),
            end_section=True,
        )

    console().print(table)


def split_quoted_string(input_string: str) -> list[str]:
    """
    Splits a string by spaces, but keeps substrings within
    single quotes, double quotes, or backticks as single tokens.

    Empty quotes are stripped.

    Examples:
        >>> split_quoted_string("this is my name")
        ['this', 'is', 'my', 'name']
        >>> split_quoted_string("I live in 'La guardia'")
        ['I', 'live', 'in', 'La guardia']
    """
    # Regex Explanation:
    # This regular expression is designed to find one of two types of patterns:
    # 1. A quoted string (single, double, or backtick quotes):
    #    - r"'[^']*'"  : Matches content inside single quotes.
    #      '           : Matches a literal single quote.
    #      [^']* : Matches any character that is NOT a single quote, zero or more times.
    #      '           : Matches the closing single quote.
    #    - r'"[^"]*"'  : Matches content inside double quotes. (Similar logic)
    #    - r"`[^`]*`"  : Matches content inside backticks. (Similar logic)
    # 2. A sequence of non-whitespace characters:
    #    - r'\S+'     : Matches one or more non-whitespace characters (for unquoted words).
    #      \S          : Matches any non-whitespace character.
    #      +           : Matches one or more times.

    # The | (OR) operator combines these patterns. The order is crucial:
    # Quoted patterns come first to ensure they are matched as a whole
    # before individual non-whitespace characters inside them are considered.
    import re

    pattern = re.compile(r"'[^']*'|\"[^\"]*\"|`[^`]*`|\S+")

    # re.findall finds all non-overlapping matches of the pattern in the string.
    matches = pattern.findall(input_string)

    # Post-process: remove the surrounding quotes from the matched substrings
    result = []
    for single_match in matches:
        # Check if the match starts and ends with any of the recognized quote types
        if (
            (single_match.startswith("'") and single_match.endswith("'"))
            or (single_match.startswith('"') and single_match.endswith('"'))
            or (single_match.startswith("`") and single_match.endswith("`"))
        ):
            result.append(single_match[1:-1])
        else:
            result.append(single_match)
    return [string for string in result if string]
