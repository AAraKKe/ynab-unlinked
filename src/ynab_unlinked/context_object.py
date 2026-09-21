from dataclasses import dataclass

from ynab_unlinked.config import ConfigV3
from ynab_unlinked.formatter import Formatter


@dataclass
class YnabUnlinkedContext[T]:
    config: ConfigV3
    formatter: Formatter
    extras: T
    show: bool = False
    reconcile: bool = False
    choose_account: bool = False
    buffer: int = 15
