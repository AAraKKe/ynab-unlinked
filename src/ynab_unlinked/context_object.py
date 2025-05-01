from dataclasses import dataclass, field

from ynab_unlinked.config import Config
from ynab_unlinked.models import Transaction


@dataclass
class YnabUnlinkedCommandObject:
    config: Config
    transactions: list[Transaction] = field(default_factory=list)
