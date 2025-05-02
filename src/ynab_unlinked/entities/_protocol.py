from pathlib import Path
from typing import Protocol

from ynab_unlinked.context_object import YnabUnlinkedContext
from ynab_unlinked.models import Transaction


class Entity(Protocol):
    def parse(self, input_file: Path, context: YnabUnlinkedContext) -> list[Transaction]:
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
        """
        ...

    def name(self) -> str:
        """
        Returns the name of the entity.
        """
        ...
