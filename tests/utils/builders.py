"""Readers for the tables the display helpers in ``ynab_unlinked.utils`` build."""

from __future__ import annotations

from unittest.mock import MagicMock

from rich.table import Table


def only_table(printed: MagicMock) -> Table:
    tables = [call.args[0] for call in printed.call_args_list if isinstance(call.args[0], Table)]
    assert len(tables) == 1, f"Expected a single table, got {len(tables)}"
    return tables[0]


def column(table: Table, header: str) -> list[str]:
    return list(next(c for c in table.columns if c.header == header).cells)


def styles(table: Table) -> list[str]:
    return [str(row.style) for row in table.rows]
