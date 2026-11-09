"""The monthly change chart of Net worth › Months: one bar per month, split by where it came from.

Each bar stacks what was saved (income minus spending), what valuation did and everything else
(money set aside, starting balances, transfers with accounts not counted), positives up and
negatives down from zero; a dot marks the month's net change. Same axis, grid, tooltip and
compact ticks as `history_chart`. Clicking a month calls back with its index.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable, Sequence
from typing import Any

from nicegui import events, ui

from ynab_unlinked.config.models.v2 import CurrencyFormat
from ynab_unlinked.core.finance import Flows
from ynab_unlinked.web.components.history_chart import compact_js, money_js
from ynab_unlinked.web.theme import Palette

CHART_HEIGHT = 260
SAVED_SLOT = 0
VALUATION_SLOT = 4

_TOOLTIP_CSS = (
    "border-radius:10px;padding:8px 10px;font-size:12px;min-width:170px;"
    "backdrop-filter:blur(14px);-webkit-backdrop-filter:blur(14px);"
    "box-shadow:0 10px 30px rgba(0,0,0,.3);"
)


def _tooltip_js(currency_format: CurrencyFormat, palette: Palette) -> str:
    return (
        "(params) => {"
        "const ps = Array.isArray(params) ? params : [params];"
        "if (!ps.length) return '';"
        f"const money = {money_js(currency_format)};"
        "const rows = ps.filter((p) => p.value !== 0 || p.seriesName === 'Net').map((p) => "
        "'<div style=\"display:flex;align-items:center;justify-content:space-between;gap:14px\">'"
        f" + '<span style=\"display:inline-flex;align-items:center;gap:6px;color:{palette.text_2}\">'"
        " + '<i style=\"display:inline-block;width:8px;height:8px;border-radius:2px;background:'"
        " + p.color + '\"></i>' + p.seriesName + '</span>'"
        " + '<b style=\"font-weight:600;font-variant-numeric:tabular-nums\">' + money(p.value)"
        " + '</b></div>').join('');"
        f"return '<div style=\"color:{palette.text_3};margin-bottom:4px\">' + ps[0].name"
        " + '</div>' + rows;"
        "}"
    )


def months_options(
    months: Sequence[tuple[dt.date, Flows]],
    palette: Palette,
    currency_format: CurrencyFormat,
    selected: int | None = None,
) -> dict[str, Any]:
    """The ECharts option for `months`; `selected` (an index) is drawn highlighted."""
    labels = [
        month.strftime("%b %Y" if month.month == 1 or i == 0 else "%b")
        for i, (month, _) in enumerate(months)
    ]
    axis_label = {"color": palette.text_3, "fontSize": 11, "fontFamily": "Inter, system-ui"}

    def bars(name: str, color: str, values: Sequence[int]) -> dict[str, Any]:
        return {
            "type": "bar",
            "name": name,
            "stack": "flows",
            "stackStrategy": "samesign",
            "color": color,
            "barMaxWidth": 26,
            "itemStyle": {"borderRadius": 3},
            "emphasis": {"disabled": True},
            "data": [
                {
                    "value": value / 1000,
                    "itemStyle": {"opacity": 1 if selected in (None, index) else 0.45},
                }
                for index, value in enumerate(values)
            ],
        }

    return {
        "animationDuration": 500,
        "textStyle": {"fontFamily": "Inter, system-ui, sans-serif"},
        "grid": {"left": 4, "right": 8, "top": 34, "bottom": 4, "containLabel": True},
        "legend": {
            "show": True,
            "top": 0,
            "left": 0,
            "icon": "roundRect",
            "itemWidth": 10,
            "itemHeight": 10,
            "itemGap": 16,
            "textStyle": {"color": palette.text_2, "fontSize": 12},
        },
        "tooltip": {
            "trigger": "axis",
            "confine": True,
            "backgroundColor": "transparent",
            "borderWidth": 0,
            "padding": 0,
            "extraCssText": (
                f"{_TOOLTIP_CSS}background:var(--surface-solid);border:1px solid var(--border-2);"
                f"color:{palette.text};"
            ),
            "axisPointer": {"type": "shadow", "shadowStyle": {"color": palette.hair}},
            ":formatter": _tooltip_js(currency_format, palette),
        },
        "xAxis": {
            "type": "category",
            "data": labels,
            "axisLine": {"show": False},
            "axisTick": {"show": False},
            "axisLabel": {**axis_label, "hideOverlap": True},
        },
        "yAxis": {
            "type": "value",
            "axisLine": {"show": False},
            "axisTick": {"show": False},
            "splitNumber": 4,
            "splitLine": {"show": True, "lineStyle": {"color": palette.hair, "width": 1}},
            "axisLabel": {**axis_label, ":formatter": compact_js(currency_format)},
        },
        "series": [
            bars("Saved", palette.series[SAVED_SLOT], [flows.saved for _, flows in months]),
            bars(
                "Valuation",
                palette.series[VALUATION_SLOT],
                [flows.valuation for _, flows in months],
            ),
            bars("Other", palette.text_3, [flows.other + flows.transfers for _, flows in months]),
            {
                "type": "scatter",
                "name": "Net",
                "color": palette.text,
                "symbolSize": 9,
                "z": 5,
                "itemStyle": {"borderColor": palette.hair, "borderWidth": 2},
                "emphasis": {"disabled": True},
                "data": [flows.change / 1000 for _, flows in months],
            },
        ],
    }


def months_chart(
    months: Sequence[tuple[dt.date, Flows]],
    palette: Palette,
    currency_format: CurrencyFormat,
    on_pick: Callable[[int], Any],
) -> ui.echart:
    """The chart, as wide as its parent; clicking a month calls `on_pick` with its index."""

    def picked(event: events.EChartPointClickEventArguments) -> Any:
        return on_pick(event.data_index)

    return ui.echart(
        months_options(months, palette, currency_format), on_point_click=picked, renderer="svg"
    ).style(f"height:{CHART_HEIGHT}px;width:100%")
