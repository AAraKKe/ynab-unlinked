"""The monthly change chart of Net worth › Months: one bar per month, split by where it came from.

Each bar stacks what was saved (income minus spending), what assets did and everything else
(money set aside, starting balances, transfers with accounts not counted; only when there is
some), positives up and negatives down from zero; a line joins the months' net changes. Same
axis, grid, tooltip and compact ticks as `history_chart`. A transparent column behind each
month takes the clicks, so the whole height of a month picks it, not only its thin bars.

`bridge_chart` is the period panel's waterfall: income up from zero, each next step from where
the one before ended, joined by dashed lines, and the net change as a bar from zero.
"""

from __future__ import annotations

import datetime as dt
import json
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
    ".toLocaleString('en-US', {month: 'short', timeZone: 'UTC'});"
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


BRIDGE_HEIGHT = 220
_BRIDGE_COLOURS = {"income": SAVED_SLOT, "spending": 1, "assets": ASSETS_SLOT}


def _bridge_js(labels: Sequence[str], connector: str, text: str) -> str:
    """Draws each step from its start to its end, its value over it, and a dashed line from
    its end to the next step."""
    return (
        "(params, api) => {"
        f"const labels = {json.dumps(list(labels))};"
        "const i = api.value(0), from = api.value(1), to = api.value(2);"
        "const a = api.coord([i, from]), b = api.coord([i, to]);"
        "const width = api.size([1, 0])[0] * 0.56;"
        "const top = Math.min(a[1], b[1]), height = Math.max(Math.abs(b[1] - a[1]), 1);"
        "const children = [{type: 'rect', shape: {x: a[0] - width / 2, y: top, width: width,"
        " height: height, r: 3}, style: api.style()},"
        " {type: 'text', style: {text: labels[i], x: a[0], y: top - 6, align: 'center',"
        f" verticalAlign: 'bottom', fill: {json.dumps(text)}, fontSize: 11,"
        " fontFamily: 'Inter, system-ui'}}];"
        "if (i < labels.length - 1) {"
        "const next = api.coord([i + 1, to]);"
        "children.push({type: 'line', shape: {x1: a[0] + width / 2, y1: b[1],"
        " x2: next[0] - width / 2, y2: b[1]},"
        f" style: {{stroke: {json.dumps(connector)}, lineWidth: 1, lineDash: [3, 3]}}}});"
        "}"
        "return {type: 'group', children: children};"
        "}"
    )


def bridge_options(
    steps: Sequence[tuple[str, int, str]],
    labels: Sequence[str],
    palette: Palette,
    currency_format: CurrencyFormat,
) -> dict[str, Any]:
    """A waterfall of `steps` (label, milliunits, kind), the last one the net change.

    Each step but the last starts where the one before it ended; the net starts at zero.
    `labels` are the values written over the bars.
    """
    data: list[dict[str, Any]] = []
    running = 0
    for index, (_, amount, kind) in enumerate(steps):
        start = 0 if kind == "net" else running
        end = amount if kind == "net" else running + amount
        running = end if kind != "net" else running
        slot = _BRIDGE_COLOURS.get(kind)
        color = (
            palette.series[slot]
            if slot is not None
            else palette.text_2
            if kind == "net"
            else palette.text_3
        )
        data.append({"value": [index, start / 1000, end / 1000], "itemStyle": {"color": color}})
    axis_label = {"color": palette.text_3, "fontSize": 11, "fontFamily": "Inter, system-ui"}
    return {
        "animationDuration": 400,
        "textStyle": {"fontFamily": "Inter, system-ui, sans-serif"},
        "grid": {"left": 4, "right": 8, "top": 24, "bottom": 4, "containLabel": True},
        "tooltip": {"show": False},
        "xAxis": {
            "type": "category",
            "data": [label for label, _, _ in steps],
            # The names stay under the chart when a step goes below zero
            "axisLine": {"show": False, "onZero": False},
            "axisTick": {"show": False},
            "axisLabel": axis_label,
        },
        "yAxis": {
            "type": "value",
            "axisLine": {"show": False},
            "axisTick": {"show": False},
            "splitNumber": 3,
            "splitLine": {"show": True, "lineStyle": {"color": palette.hair, "width": 1}},
            "axisLabel": {**axis_label, ":formatter": compact_js(currency_format)},
        },
        "series": [
            {
                "type": "custom",
                "name": "bridge",
                ":renderItem": _bridge_js(labels, palette.text_3, palette.text_2),
                "encode": {"x": 0, "y": [1, 2]},
                "data": data,
                # Zero stands out, so spending that goes past what came in reads as going below
                "markLine": {
                    "silent": True,
                    "symbol": "none",
                    "label": {"show": False},
                    "lineStyle": {"color": palette.text_3, "type": "solid", "width": 1},
                    "data": [{"yAxis": 0}],
                },
            }
        ],
    }


def bridge_chart(
    steps: Sequence[tuple[str, int, str]],
    labels: Sequence[str],
    palette: Palette,
    currency_format: CurrencyFormat,
) -> ui.echart:
    return ui.echart(bridge_options(steps, labels, palette, currency_format), renderer="svg").style(
        f"height:{BRIDGE_HEIGHT}px;width:100%"
    )
