from pathlib import Path
from typing import NamedTuple, Protocol

from ynab_unlinked.models import Transaction


class Match(NamedTuple):
    """How sure an entity is that it can read a file, and why."""

    confidence: float
    """0.0 (no) to 1.0 (certain)."""
    reason: str
    """Short and user facing: "BBVA header row found"."""


class Entity(Protocol):
    def parse(self, input_file: Path) -> list[Transaction]:
        """
        Parse an input file into a list of Transaction objects.

        This is the main method of the EntityParser protocol. Any input file can be converted
        into an abstraction of Transaction objects. These objects only contain information
        related with the transactions themselves:
        - Date
        - Payee
        - Amount

        `ynab-unlinked` will understand these transactions and enrich them when necesary to
        ensure the best matching when pushing them to YNAB.

        Every option (a language, a year) is bound when the entity is built
        (`LoaderSpec.build`); parsing reads only the file. A row that cannot be read raises
        `ParsingError` naming its line or row.
        """
        ...

    def name(self) -> str:
        """
        Returns the name of the entity.
        """
        ...

    def sniff(self, input_file: Path) -> Match:
        """
        Tell whether `input_file` looks like an export of this entity.

        It must be cheap (first rows, first page or first KB of the file), must not depend on
        the options the entity was built with and must never raise: a file that cannot be
        read is a confidence of 0 with the reason.
        """
        ...
