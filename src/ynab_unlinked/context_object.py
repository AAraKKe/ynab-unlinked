from dataclasses import dataclass

from ynab_unlinked.config import Config


@dataclass
class YnabUnlinkedContext[T]:
    config: Config
    extras: T
    show: bool = False
    reconcile: bool = False
