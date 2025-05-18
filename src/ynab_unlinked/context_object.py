from dataclasses import dataclass

from ynab_unlinked.config import ConfigV1


@dataclass
class YnabUnlinkedContext[T]:
    config: ConfigV1
    extras: T
    show: bool = False
    reconcile: bool = False
