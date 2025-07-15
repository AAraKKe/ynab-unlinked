import datetime as dt
from dataclasses import dataclass
from pathlib import Path

import typer

from ynab_unlinked.commands import load
from ynab_unlinked.context_object import YnabUnlinkedContext
from ynab_unlinked.entities import Entity
from ynab_unlinked.models import Transaction
from ynab_unlinked.process import process_transactions
from ynab_unlinked.utils import MAX_PAST_TRANSACTIONS_SHOWN

from .types import LoadEntityCallback


@dataclass
class StubEntity(Entity):
    transactions: list[Transaction]

    def parse(self, input_file: Path, context: YnabUnlinkedContext) -> list[Transaction]:
        return self.transactions

    def name(self) -> str:
        return "test"


def load_entity() -> LoadEntityCallback:
    """
    Load a stub entity that always returns a given set of transactions for testing.

    This entity is avialable through the load command in the test suit and is associated
    with the TestAccountID account id.
    """

    def callback(current_date: dt.datetime, transactions: list[Transaction] | None = None):
        if transactions is None:
            transactions = [
                Transaction(current_date - dt.timedelta(1), "Test Payee 1", 10.00),
                Transaction(current_date - dt.timedelta(2), "Test Payee 2", -10.00),
                Transaction(
                    current_date - dt.timedelta(MAX_PAST_TRANSACTIONS_SHOWN + 1),
                    "Test Payee 3",
                    -0.15,
                ),
            ]

        def command(context: typer.Context):
            ctx: YnabUnlinkedContext = context.obj

            process_transactions(
                StubEntity(transactions=transactions), input_file=Path(), context=ctx
            )

        load.command(name="test")(command)

    return callback
