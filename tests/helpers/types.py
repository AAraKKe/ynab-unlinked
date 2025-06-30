import datetime as dt
from typing import Protocol

from typer.testing import Result

from ynab_unlinked.models import Transaction


class CliRunner(Protocol):
    def __call__(self, *args: str, input: str | None = None) -> Result: ...


class LoadEntityCallback(Protocol):
    def __call__(
        self, current_date: dt.datetime, transactions: list[Transaction] | None = None
    ): ...
