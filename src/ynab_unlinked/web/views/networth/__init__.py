"""Net worth: the history chart, the four buckets, and the accounts with balance updates.

`data` holds what is worked out without NiceGUI (ranges, the store snapshot, the table order,
the by hand pill, the balance write); `view` draws the page, `table` the accounts card with its
inline editor, `drawer` the account drawer.
"""

from __future__ import annotations

from ynab_unlinked.web.views.networth.data import (
    MAX_PICKED,
    Snapshot,
    assign_slots,
    by_hand_pill,
    last_set,
    load_snapshot,
    range_start,
    table_order,
)
from ynab_unlinked.web.views.networth.view import NetWorthView, networth_view

__all__ = [
    "MAX_PICKED",
    "NetWorthView",
    "Snapshot",
    "assign_slots",
    "by_hand_pill",
    "last_set",
    "load_snapshot",
    "networth_view",
    "range_start",
    "table_order",
]
