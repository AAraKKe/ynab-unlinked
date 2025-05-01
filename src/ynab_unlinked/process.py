import datetime as dt
from collections.abc import Generator
from typing import List

from rich import print
from rich.prompt import Confirm
from rich.status import Status

from ynab_unlinked import display, utils
from ynab_unlinked.config import TRANSACTION_GRACE_PERIOD_DAYS, Config
from ynab_unlinked.context_object import YnabUnlinkedCommandObject
from ynab_unlinked.models import MatchStatus, Transaction, TransactionWithYnabData
from ynab_unlinked.ynab_api.client import Client

# Request transactions to the YNAB API from the last checkpoint date minus 10 days for buffer
TRANSACTIONS_DAYES_BEFORE_LAST_EXTRACTION = 10


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


def filter_transactions(
    transactions: list[Transaction], config: Config
) -> Generator[Transaction, None, None]:
    #    if config.checkpoint is None:
    yield from transactions
    return

    # This is dead code due to the early return above, kept for future implementation
    yield from (
        t for t in transactions if t.date >= config.checkpoint.latest_date_processed
    )


def process_transactions(
    parsed_input: List[Transaction],
    config: Config,
    show: bool,
    reconcile: bool,
) -> None:
    """
    Process the transactions from the input file, match them with YNAB data, and upload them to YNAB.

    Args:
        parsed_input: List of transactions from the input file
        config: YNAB configuration
        reconcile: Whether to reconcile cleared transactions
        show: Just show the transactions without processing them
    """

    preprocess_transactions(parsed_input, config)

    if show:
        display.transaction_table(parsed_input)
        return

    transactions = [
        TransactionWithYnabData(t)
        for t in filter_transactions(
            parsed_input,
            config,
        )
    ]
    client = Client(config)

    with Status("Reading transactions..."):
        ynab_transactions = client.transactions(
            since_date=(
                config.checkpoint.latest_date_processed
                - dt.timedelta(days=TRANSACTIONS_DAYES_BEFORE_LAST_EXTRACTION)
                if config.checkpoint
                else None
            )
        )
    print("[bold green]✔ Transactions read")

    with Status("Augmenting transactions..."):
        utils.augmnet_transactions(
            transactions, ynab_transactions, client, reconcile
        )
    print("[bold green]✔ Transactions augmneted with YNAB information")

    display.transactions_to_upload(transactions)

    if not any(t.needs_creation or t.needs_update for t in transactions):
        print("[bold blue]🎉 All done! Nothing to do.")
        config.update_and_save(transactions[0])
        return

    if any(t.match_status == MatchStatus.PARTIAL_MATCH for t in transactions):
        display.partial_matches(transactions)
        print(
            "\nIf these partial matches are ok, you can accept them and update the transactions in YNAB.\n"
            "If you don't accept them, new transactions will be created instead."
        )
        final_matching = (
            MatchStatus.MATCHED
            if Confirm.ask("Do you want to accept these matches?")
            else MatchStatus.UNMATCHED
        )
        for t in transactions:
            if t.match_status == MatchStatus.PARTIAL_MATCH and t.needs_update:
                t.match_status = final_matching
                if final_matching == MatchStatus.UNMATCHED:
                    t.reset_matching()

    with Status("Preparing transactions to upload..."):
        new_transactions = [t for t in transactions if t.needs_creation]
        transactions_to_update = [t for t in transactions if t.needs_update]

    print(f"[bold]New transactions:       {len(new_transactions)}")
    print(f"[bold]Transactions to update: {len(transactions_to_update)}")

    if Confirm.ask("Do you want to continue and create the transactions?"):
        with Status("Creating/Updating transactions..."):
            client.create_transactions(new_transactions)
            client.update_transactions(transactions_to_update)

    config.update_and_save(transactions[0])

    print("[bold blue]🎉 All done!")
