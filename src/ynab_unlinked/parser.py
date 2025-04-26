from pathlib import Path
from typing import Protocol

from ynab_unlinked.config import Config
from ynab_unlinked.models import Transaction



class Parser(Protocol):
    def parse(self, input_file: Path, config: Config) -> list[Transaction]: ...
