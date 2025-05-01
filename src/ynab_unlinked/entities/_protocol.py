from enum import StrEnum
from pathlib import Path
from typing import Protocol

from ynab_unlinked.config import Config
from ynab_unlinked.models import Transaction


class InputType(StrEnum):
    TXT = "txt"
    CSV = "csv"


class EntityParser(Protocol):
    def parse(self, input_file: Path, config: Config) -> list[Transaction]:
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

    def supports_input_type(self, input_type: InputType) -> bool:
        """
        Returns True if the EntityParser ipmlementing this protocol is able to process
        a given input type.
        """
        ...
