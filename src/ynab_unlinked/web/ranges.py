"""The range the finance pages show (1M … All), remembered across pages and visits.

Net worth, Cash flow and Spending read the same months, so a range picked on one is the range
of the others, and the one the app opens with next time. Kept in the browser's preferences.
"""

from __future__ import annotations

from ynab_unlinked.web.finances import RANGES
from ynab_unlinked.web.storage import user_storage

_RANGE_KEY = "yul.range"


def saved_range(default: str) -> str:
    """The range picked last, `default` before any was (or outside a browser session)."""
    try:
        value = user_storage().get(_RANGE_KEY)
    except RuntimeError:
        return default
    return value if isinstance(value, str) and value in RANGES else default


def save_range(key: str) -> None:
    if key in RANGES:
        user_storage()[_RANGE_KEY] = key
