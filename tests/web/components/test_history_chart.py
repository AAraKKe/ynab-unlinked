import datetime as dt
from collections.abc import Callable, Mapping
from typing import Any

import pytest

from ynab_unlinked.config.models.v2 import CurrencyFormat
from ynab_unlinked.core.cashflow import FlowMonth
from ynab_unlinked.core.finance import Flows
from ynab_unlinked.core.history import Point
from ynab_unlinked.web import theme
from ynab_unlinked.web.components.cashflow_chart import (
    category_months_options,
    income_spending_options,
    rate_options,
)
from ynab_unlinked.web.components.flow_chart import months_options
from ynab_unlinked.web.components.history_chart import (
    NOTE_LENGTH,
    ChartSeries,
    history_options,
    note_html,
    note_js,
)

PALETTE = theme.DARK_PALETTE
FORMAT = CurrencyFormat(
    iso_code="EUR",
    decimal_digits=2,
    decimal_separator=".",
    symbol_first=False,
    group_separator=",",
    currency_symbol="€",
    display_symbol=True,
)
MARCH = dt.date(2026, 3, 1)
NOTES = {MARCH: "Sold the <old> car\n\n  Paid the garage  ", dt.date(2025, 3, 1): "Another year"}
FLOW_MONTHS = [FlowMonth(MARCH, 3_000_000, 1_000_000, True, note="Sold the <old> car")]

Notes = Mapping[dt.date, str] | None


def test_a_note_is_escaped_and_keeps_its_lines_without_the_blank_ones():
    assert note_html(NOTES[MARCH]) == "Sold the &lt;old&gt; car<br>Paid the garage"


def test_a_long_note_is_cut():
    told = note_html("word " * 200)

    assert len(told) == NOTE_LENGTH
    assert told.endswith("word…")


def test_only_the_notes_of_the_months_drawn_reach_the_browser():
    script = note_js(NOTES, [dt.date(2026, 3, 14), "2026-04"], PALETTE)

    assert '"2026-03": "Sold the &lt;old&gt; car<br>Paid the garage"' in script
    assert "Another year" not in script


@pytest.mark.parametrize(
    "options",
    [
        pytest.param(
            lambda notes: income_spending_options(FLOW_MONTHS, PALETTE, FORMAT, notes),
            id="income and spending",
        ),
        pytest.param(
            lambda notes: rate_options(FLOW_MONTHS, PALETTE, 0.5, notes), id="savings rate"
        ),
        pytest.param(
            lambda notes: category_months_options(
                ["2026-03"], [1_000_000], PALETTE, FORMAT, 1_000_000, notes=notes
            ),
            id="a category's months",
        ),
        pytest.param(
            lambda notes: months_options(
                [(MARCH, Flows(income=3_000_000))], PALETTE, FORMAT, notes=notes
            ),
            id="net worth by month",
        ),
        pytest.param(
            lambda notes: history_options(
                [ChartSeries("Net worth", [Point(dt.date(2026, 3, 14), 1)], "#3b82f6")],
                PALETTE,
                FORMAT,
                notes,
            ),
            id="net worth by day",
        ),
    ],
)
def test_the_tooltip_of_a_month_says_its_whole_note(options: Callable[[Notes], dict[str, Any]]):
    tooltip = options(NOTES)["tooltip"][":formatter"]

    assert "Sold the &lt;old&gt; car<br>Paid the garage" in tooltip
    assert "Another year" not in tooltip
    assert "Paid the garage" not in options(None)["tooltip"][":formatter"]
