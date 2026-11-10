from collections.abc import Sequence

from rich import box
from rich.prompt import Prompt
from rich.rule import Rule
from rich.style import Style
from rich.table import Column, Table
from rich.text import Text

from ynab_unlinked.cli.display import CliProgress, console, info, process, question
from ynab_unlinked.config import get_config
from ynab_unlinked.config.budget import budget_from_plan
from ynab_unlinked.config.models.v2 import Budget
from ynab_unlinked.core.importing import ImportRow, RowStatus
from ynab_unlinked.formatter import Formatter
from ynab_unlinked.models import Transaction
from ynab_unlinked.text import YNAB_TOKEN_URL
from ynab_unlinked.ynab_api.client import Client

IMPORT_HELP_MESSAGE = (
    "The table below shows the transactions to be imported to YNAB.\n"
    " - The [green]green[/] rows are new transactions to be imported.\n"
    " - The [gray37]dimmed[/] rows are already in YNAB and will not be sent again.\n"
    " - The [gray37]matched[/] rows were matched in YNAB with a transaction you had entered "
    "by hand: they are there too.\n"
    " - The [gray37 strike]crossed out[/] rows were left out of imports in `yul app` and are "
    "never sent.\n"
    "YNAB matches every imported transaction against the ones you entered yourself on the same "
    "account, so the payee shown here is the one from the bank export, not the final one."
)

_STATUS: dict[RowStatus, tuple[str, Style]] = {
    RowStatus.NEW: ("new", Style(color="green")),
    RowStatus.IN_YNAB: ("in YNAB", Style(color="gray37")),
    RowStatus.MATCHED: ("matched in YNAB", Style(color="gray37")),
    RowStatus.EXCLUDED: ("left out", Style(color="gray37", strike=True)),
}


def prompt_for_api_key() -> str:
    info(f"Create a Personal Access Token in YNAB: {YNAB_TOKEN_URL}")
    return question("What is the API Key to connect to YNAB?", password=True)


def prompt_for_budget(api_key: str | None = None) -> Budget:
    # If no api_key is provided, try to get it from the config
    if api_key is None:
        with CliProgress() as progress:
            config = get_config(progress)
        if config is None:
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
    budget_details = client.budget(str(selected_budget.id))

    return budget_from_plan(budget_details)


def _flows(amount: float, formatter: Formatter) -> tuple[str, str]:
    amount_str = formatter.format_amount(amount)
    return (amount_str if amount > 0 else "", amount_str if amount < 0 else "")


def display_transaction_table(transactions: list[Transaction], formatter: Formatter):
    columns = [
        Column(header="Date", justify="left", max_width=10),
        Column(header="Payee", justify="left", width=50),
        Column(header="Inflow", justify="right", max_width=15),
        Column(header="Outflow", justify="right", max_width=15),
    ]
    table = Table(*columns, title="Transactions to process", box=box.SIMPLE)

    for transaction in transactions:
        inflow, outflow = _flows(transaction.amount, formatter)
        table.add_row(
            formatter.format_date(transaction.date),
            # Bank text, never markup: a payee with `[/]` would not render
            Text(transaction.payee),
            inflow,
            outflow,
        )

    console().print(table)


def display_import_table(rows: Sequence[ImportRow], formatter: Formatter):
    if not rows:
        return

    columns = [
        Column(header="Date", justify="left", max_width=10),
        Column(header="Payee", justify="left", width=50),
        Column(header="Inflow", justify="right", max_width=15),
        Column(header="Outflow", justify="right", max_width=15),
        Column(header="Status", justify="left", max_width=16),
    ]
    table = Table(*columns, title="Transactions to import", box=box.SIMPLE)

    for row in rows:
        inflow, outflow = _flows(row.transaction.amount, formatter)
        status, style = _STATUS[row.status]
        table.add_row(
            formatter.format_date(row.transaction.date),
            Text(row.transaction.payee),
            inflow,
            outflow,
            status,
            style=style,
        )

    console().print(Rule("Transactions to be imported"))
    console().print(IMPORT_HELP_MESSAGE)
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
    matches: list[str] = pattern.findall(input_string)

    # Post-process: remove the surrounding quotes from the matched substrings
    result: list[str] = []
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
