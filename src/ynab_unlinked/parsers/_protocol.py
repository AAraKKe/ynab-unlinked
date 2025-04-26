from pathlib import Path
from typing import Protocol
from enum import StrEnum

from ynab_unlinked.config import Config
from ynab_unlinked.models import Transaction


class InputType(StrEnum):
    TXT = "txt"
    CSV = "csv"


class Parser(Protocol):
    def parse(self, input_file: Path, config: Config) -> list[Transaction]: ...
    def is_valid_input_type(self, input_type: InputType) -> bool: ...
