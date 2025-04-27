from collections.abc import Generator
import datetime as dt
from pathlib import Path
from typing_extensions import Annotated
from typing import assert_never

import typer
from rich import print
from rich.status import Status
from rich.prompt import Prompt, Confirm

from ynab_unlinked.config import ensure_config, Config, TRANSACTION_GRACE_PERIOD_DAYS
from ynab_unlinked.client import Client
from ynab_unlinked.parsers import ParserType, InputType, get_parser
from ynab_unlinked import display, utils
from ynab_unlinked.models import Transaction, TransactionWithYnabData


app = typer.Typer(name="ynab-unlinked", no_args_is_help=True)


def prompt_for_config():
    print("[bold]Welcome to ynab-unlinked! Lets setup your connection")
    api_key = Prompt.ask("What is the API Key to connect to YNAB?", password=True)
    client = Client(Config(api_key=api_key, budget_id="", account_id=""))

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
    assert budget.accounts is not None, "Unexpeted. Budget does not have accounts"

    print(f"[bold]Selected budget: {budget.name}")

    print("The budget contains the following accounts:")
    accounts = [acc for acc in budget.accounts if not acc.closed]
    for idx, acc in enumerate(accounts):
        print(f" - {idx + 1}. {acc.name}")

    acc_num = Prompt.ask(
        "What account are the transactions going to be imported to? (By number)",
        choices=[str(i) for i in range(1, len(accounts) + 1)],
        show_choices=False,
    )
    account = accounts[int(acc_num) - 1]

    print(f"[bold]Account selected: {account.name}")

    config = Config(api_key=api_key, budget_id=budget.id, account_id=account.id)
    config.save()

    print("[bold green]All done!")
    return config


def filter_transactions(
    transactions: list[Transaction], config: Config
) -> Generator[Transaction, None, None]:
    if config.checkpoint is None:
        yield from transactions
        return

    yield from (
        t for t in transactions if t.date >= config.checkpoint.latest_date_processed
    )


def add_past_to_transactions(transactions: list[Transaction], config: Config):
    if config.checkpoint is None:
        return

    for t in transactions:
        if t.date < config.checkpoint.latest_date_processed + dt.timedelta(
            days=TRANSACTION_GRACE_PERIOD_DAYS
        ):
            t.past = True


def preprocess_transactions(transactions: list[Transaction], config: Config):
    add_past_to_transactions(transactions, config)


@app.command()
def cli(
    input_file: Annotated[
        Path,
        typer.Argument(
            exists=True,
            file_okay=True,
            dir_okay=False,
            readable=True,
            help="The input file with the CC transations",
        ),
    ],
    parser: Annotated[
        ParserType,
        typer.Option(help="Parser to parse the input file"),
    ] = ParserType.SABADELL,
    input_type: Annotated[
        InputType, typer.Option(help="The type of the input file.")
    ] = InputType.TXT,
    parse_only: Annotated[
        bool, typer.Option(help="Just parse the input to view transactions")
    ] = False,
    reconcile: Annotated[
        bool, typer.Option(help="Reconcile cleared transactions")
    ] = False,
):
    """
    Create transations in your YNAB account from a list of transactions from Sbadell export of a credit card.
    \n

    Process INPUT-FILE, that contains a list of credit card transactions from Sabadell, and create transactions in your ynab account.

    \n
    The first time the command is run you will be asked some questions to setup your YNAB connection. After that,
    transaction processing won't require any input unless there are some actions to take for specific transactions.
    """

    config = Config.load() if ensure_config() else prompt_for_config()

    _parser = get_parser(parser)
    if not _parser.supports_input_type(input_type):
        print(
            f"[bold red]The parser '{parser}' does not support input type '{input_type}'"
        )
        raise typer.Exit()

    parsed_input = sorted(
        _parser.parse(input_file, config),
        key=lambda t: t.date,
        reverse=True,
    )
    preprocess_transactions(parsed_input, config)

    if parse_only:
        display.transaction_table(parsed_input)
        raise typer.Exit()

    transactions = [
        TransactionWithYnabData(t)
        for t in filter_transactions(
            _parser.parse(input_file, config),
            config,
        )
    ]
    client = Client(config)

    with Status("Reading transactions..."):
        ynab_transactions = client.transactions(
            since_date=(
                config.checkpoint.latest_date_processed if config.checkpoint else None
            )
        )
    print("[bold green]✔ Transactions read")

    with Status("Augmenting transactions..."):
        utils.augmnet_transactions(transactions, ynab_transactions, client, reconcile)
    print("[bold green]✔ Transactions augmneted with YNAB information")

    with Status("Preparing transactions to upload..."):
        new_transactions = [t for t in transactions if t.needs_creation]
        transactions_to_update = [t for t in transactions if t.needs_update]

    print("[bold green]✔ Transactions prepared")

    display.transactions_to_upload(transactions)

    if not new_transactions and not transactions_to_update:
        print("[bold blue]🎉 All done! Nothing to do.")
        config.update_and_save(transactions[0])
        raise typer.Exit()

    print(f"[bold]New transactions:      {len(new_transactions)}")
    print(f"[bold]Transactions to update {len(transactions_to_update)}")

    if Confirm.ask("Do you want to continue and create the transactions?"):
        with Status("Creating/Updating transactions..."):
            client.create_transactions(new_transactions)
            client.update_transactions(transactions_to_update)

    config.update_and_save(transactions[0])

    print("[bold blue]🎉 All done!")


def main():
    app()


if __name__ == "__main__":
    main()
