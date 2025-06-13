from dataclasses import dataclass

from ynab_unlinked.config import ConfigV2


@dataclass
class YnabUnlinkedContext[T]:
    config: ConfigV2
    extras: T
    show: bool = False
    reconcile: bool = False
