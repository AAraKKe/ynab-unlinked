from dataclasses import dataclass

from ynab_unlinked.config import LatestConfig
from ynab_unlinked.formatter import Formatter


@dataclass
class YnabUnlinkedContext:
    """The state of one `yul` command line run. The CLI only: parsers never see it."""

    config: LatestConfig
    formatter: Formatter
    show: bool = False
    reconcile: bool = False
    choose_account: bool = False
    buffer: int = 15
    yes: bool = False
