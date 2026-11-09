"""The monthly change chart of Net worth › Months: one bar per month, split by where it came from.

Each bar stacks what was saved (income minus spending), what assets did and everything else
(money set aside, starting balances, transfers with accounts not counted; only when there is
some), positives up and negatives down from zero; a line joins the months' net changes. Same
axis, grid, tooltip and compact ticks as `history_chart`. A transparent column behind each
month takes the clicks, so the whole height of a month picks it, not only its thin bars.
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
ASSETS_SLOT = 4
HIT_SERIES = "month"

# Draws a transparent rectangle over the whole height of each month
_COLUMN_JS = (
    "(params, api) => {"
    "const x = api.coord([api.value(0), 0])[0];"
    "const width = api.size([1, 0])[0];"
    "const box = params.coordSys;"
    "return {type: 'rect', shape: {x: x - width / 2, y: box.y, width: width, height: box.height},"
    " style: {fill: 'rgba(0,0,0,0)'}};"
    "}"
)

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
        "const rows = ps.filter((p) => p.seriesType !== 'custom'"
        " && (p.value !== 0 || p.seriesName === 'Net')).map((p) => "
        "'<div style=\"display:flex;align-items:center;justify-content:space-between;gap:14px\">'"
        f" + '<span style=\"display:inline-flex;align-items:center;gap:6px;color:{palette.text_2}\">'"
        " + '<i style=\"display:inline-block;width:8px;height:8px;border-radius:2px;background:'"
        " + p.color + '\"></i>' + p.seriesName + '</span>'"
        " + '<b style=\"font-weight:600;font-variant-numeric:tabular-nums\">' + money(p.value)"
        " + '</b></div>').join('');"
        f"return '<div style=\"color:{palette.text_3};margin-bottom:4px\">'"
        f" + ({_MONTH_JS})(ps[0].name, 1, true)"
        " + '</div>' + rows;"
        "}"
    )


# `2026-09` as `Sep`, `Sep 2026` for the first month and every January (or always with `full`)
_MONTH_JS = (
    "(value, index, full) => {"
    "const [year, month] = String(value).split('-');"
    "const name = new Date(Date.UTC(+year, +month - 1, 1))"
    ".toLocaleString('en-GB', {month: 'short', timeZone: 'UTC'});"
    "return full || index === 0 || month === '01' ? name + ' ' + year : name;"
    "}"
)
_RADIUS = 3


def _corners(months: Sequence[Sequence[int]]) -> list[list[list[int]]]:
    """Per stacked series and month, the corners to round: only the two ends of a month's bar.

    Segments that meet stay square, so a month reads as one bar split into parts. `months`
    holds each month's values in stacking order; positives stack up, negatives down.
    """
    corners = [[[0, 0, 0, 0] for _ in months] for _ in (months[0] if months else ())]
    for index, values in enumerate(months):
        top = max((i for i, v in enumerate(values) if v > 0), default=None)
        bottom = max((i for i, v in enumerate(values) if v < 0), default=None)
        if top is not None:
            corners[top][index] = [_RADIUS, _RADIUS, 0, 0]
        if bottom is not None:
            corners[bottom][index] = [0, 0, _RADIUS, _RADIUS]
    return corners


def months_options(
    months: Sequence[tuple[dt.date, Flows]],
    palette: Palette,
    currency_format: CurrencyFormat,
    selected: int | None = None,
) -> dict[str, Any]:
    """The ECharts option for `months`; `selected` (an index) is drawn highlighted."""
    # Unique keys, so a click on a month's name finds it; the axis writes them as names
    keys = [month.strftime("%Y-%m") for month, _ in months]
    axis_label = {"color": palette.text_3, "fontSize": 11, "fontFamily": "Inter, system-ui"}

    def faded(index: int) -> float:
        return 1 if selected in (None, index) else 0.35

    others = [flows.other + flows.transfers for _, flows in months]
    stacked = [
        [flows.saved for _, flows in months],
        [flows.assets for _, flows in months],
        *([others] if any(others) else []),
    ]
    corners = _corners([list(values) for values in zip(*stacked, strict=True)])

    def bars(name: str, color: str, slot: int) -> dict[str, Any]:
        return {
            "type": "bar",
            "name": name,
            "stack": "flows",
            "stackStrategy": "samesign",
            "color": color,
            "barMaxWidth": 26,
            "emphasis": {"disabled": True},
            "data": [
                {
                    "value": value / 1000,
                    "itemStyle": {"opacity": faded(index), "borderRadius": corners[slot][index]},
                }
                for index, value in enumerate(stacked[slot])
            ],
        }

    legend = ["Saved", "Assets", *(["Other"] if any(others) else []), "Net"]
    return {
        "animationDuration": 500,
        "textStyle": {"fontFamily": "Inter, system-ui, sans-serif"},
        "grid": {"left": 4, "right": 8, "top": 34, "bottom": 4, "containLabel": True},
        "legend": {
            "show": True,
            "data": legend,
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
            "data": keys,
            "triggerEvent": True,
            "axisLine": {"show": False},
            "axisTick": {"show": False},
            "axisLabel": {
                **axis_label,
                "hideOverlap": True,
                "cursor": "pointer",
                ":formatter": f"(value, index) => ({_MONTH_JS})(value, index, false)",
            },
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
            {
                "type": "custom",
                "name": HIT_SERIES,
                ":renderItem": _COLUMN_JS,
                "z": 0,
                "silent": False,
                "tooltip": {"show": False},
                "data": [[index] for index in range(len(months))],
            },
            bars("Saved", palette.series[SAVED_SLOT], 0),
            bars("Assets", palette.series[ASSETS_SLOT], 1),
            *([bars("Other", palette.text_3, 2)] if len(stacked) > 2 else []),
            {
                "type": "line",
                "name": "Net",
                "color": palette.text,
                "symbol": "circle",
                "symbolSize": 8,
                "z": 5,
                "lineStyle": {"width": 1.5, "cap": "round", "join": "round"},
                "itemStyle": {"borderColor": palette.hair, "borderWidth": 2},
                "emphasis": {"disabled": True},
                "data": [
                    {"value": flows.change / 1000, "itemStyle": {"opacity": faded(index)}}
                    for index, (_, flows) in enumerate(months)
                ],
            },
        ],
    }


def months_chart(
    months: Sequence[tuple[dt.date, Flows]],
    palette: Palette,
    currency_format: CurrencyFormat,
    on_pick: Callable[[int], Any],
    selected: int | None = None,
) -> ui.echart:
    """The chart, as wide as its parent; clicking a month (anywhere in its column) calls
    `on_pick` with its index."""

    keys = [month.strftime("%Y-%m") for month, _ in months]

    def clicked(event: events.GenericEventArguments) -> Any:
        args = event.args
        if args.get("componentType") == "series" and isinstance(args.get("dataIndex"), int):
            return on_pick(args["dataIndex"])
        if args.get("componentType") == "xAxis" and args.get("value") in keys:
            return on_pick(keys.index(args["value"]))
        return None

    chart = ui.echart(months_options(months, palette, currency_format, selected), renderer="svg")
    chart.on("componentClick", clicked, ["componentType", "dataIndex", "value"])
    return chart.style(f"height:{CHART_HEIGHT}px;width:100%")
