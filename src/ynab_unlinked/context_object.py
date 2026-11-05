from dataclasses import dataclass

from ynab_unlinked.config import LatestConfig
from ynab_unlinked.formatter import Formatter


@dataclass
class YnabUnlinkedContext[T]:
    config: LatestConfig
    formatter: Formatter
    extras: T
    show: bool = False
    reconcile: bool = False
    choose_account: bool = False
    buffer: int = 15
    yes: bool = False
