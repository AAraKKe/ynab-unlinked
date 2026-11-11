"""The charts of the Plan, in the look of `history_chart`: what was, then what the plan says.

Every series of a chart is given one value per day of the same axis, None where it has none.
A day without a value is not a point of the series, so the tooltip of a day lists the series
that stand on it and nothing borrowed from a neighbour.

- `worth_options`: net worth so far, the plan, the plan of what was measured (dashed, drawn
  only when the plan differs) and the range around the plan as a soft band.
- `types_options`: the same plan split in assets, savings and cash, stacked from zero.
- `goal_options`: what the goal held, where the plan takes it, and its target as a line.

A dashed vertical line marks today in all three. Amounts are whole units: decimals of a
figure ten years away would be noise.
"""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Sequence
from typing import Any

from ynab_unlinked.config.models.v2 import CurrencyFormat
from ynab_unlinked.web.components.history_chart import compact_js, money_js
from ynab_unlinked.web.theme import Palette

WORTH_HEIGHT = 360
GOAL_HEIGHT = 240
SO_FAR = "So far"
PLAN = "The plan"
MEASURED = "As measured"
RANGE = "Assets ±2 pts a year"
LOW_ID = "low"
WIDTH_ID = "width"
_BAND_OPACITY = 0.14
_STACK_OPACITY = 0.55

Values = Sequence[float | None]
"""Milliunits, one per day of the chart's axis."""

_TOOLTIP_CSS = (
    "border-radius:10px;padding:8px 10px;font-size:12px;min-width:180px;"
    "backdrop-filter:blur(14px);-webkit-backdrop-filter:blur(14px);"
    "box-shadow:0 10px 30px rgba(0,0,0,.3);"
)


def _tooltip_js(
    currency_format: CurrencyFormat, palette: Palette, *, skip: Sequence[str], total: bool
) -> str:
    """Month and year, a row per series that has a value that day, then the range around
    the plan or the total of the stack."""
    row = (
        "const row = (color, name, text) => "
        "'<div style=\"display:flex;align-items:center;justify-content:space-between;gap:14px\">'"
        f" + '<span style=\"display:inline-flex;align-items:center;gap:6px;color:{palette.text_2}\">'"
        " + '<i style=\"display:inline-block;width:10px;height:2px;border-radius:1px;background:'"
        " + color + '\"></i>' + esc(name) + '</span>'"
        " + '<b style=\"font-weight:600;font-variant-numeric:tabular-nums\">' + text + '</b></div>';"
    )
    extra = (
        "if (shown.length > 1) rows += row('transparent', 'Total', "
        "money(shown.reduce((sum, p) => sum + p.value[1], 0)));"
        if total
        else (
            f"const low = ps.find((p) => p.seriesId === {json.dumps(LOW_ID)});"
            f"const width = ps.find((p) => p.seriesId === {json.dumps(WIDTH_ID)});"
            f"if (low && width) rows += row('transparent', {json.dumps(RANGE)}, "
            "compact(low.value[1]) + ' – ' + compact(low.value[1] + width.value[1]));"
        )
    )
    return (
        "(params) => {"
        "const ps = (Array.isArray(params) ? params : [params]).filter((p) => p.value[1] != null);"
        "if (!ps.length) return '';"
        f"const money = {money_js(currency_format, 0)};"
        f"const compact = {compact_js(currency_format)};"
        f"const skip = {json.dumps(list(skip))};"
        "const esc = (s) => String(s).replace(/[&<>\"']/g, (c) => "
        "({'&': '&amp;', '<': '&lt;', '>': '&gt;', '\"': '&quot;', \"'\": '&#39;'})[c]);"
        f"{row}"
        "const day = new Date(ps[0].value[0]).toLocaleDateString('en-GB', "
        "{month: 'short', year: 'numeric', timeZone: 'UTC'});"
        "const shown = ps.filter((p) => p.seriesName && !skip.includes(p.seriesName));"
        "let rows = shown.map((p) => row(p.color, p.seriesName, money(p.value[1]))).join('');"
        f"{extra}"
        f"return '<div style=\"color:{palette.text_3};margin-bottom:4px\">' + day + '</div>' + rows;"
        "}"
    )


def _data(days: Sequence[dt.date], values: Values) -> list[list[Any]]:
    return [
        [day.isoformat(), round(value / 1000, 2)]
        for day, value in zip(days, values, strict=True)
        if value is not None
    ]


def _line(
    name: str,
    color: str,
    data: list[list[Any]],
    *,
    palette: Palette,
    currency_format: CurrencyFormat,
    dashed: bool = False,
    visible: bool = True,
    end_label: bool = False,
) -> dict[str, Any]:
    return {
        "type": "line",
        "name": name,
        "color": color,
        "showSymbol": False,
        "symbol": "circle",
        "symbolSize": 7,
        "connectNulls": False,
        # Always present, transparent when hidden: a chart keeps the series it had when the
        # number of them does not change
        "lineStyle": {
            "width": 2,
            "cap": "round",
            "join": "round",
            "type": "dashed" if dashed else "solid",
            "opacity": 1 if visible else 0,
        },
        "emphasis": {"disabled": True},
        "endLabel": {
            "show": end_label and visible,
            "color": palette.text_2,
            "fontSize": 11.5,
            "distance": 8,
            ":formatter": f"(p) => ({compact_js(currency_format)})(p.value[1])",
        },
        "labelLayout": {"moveOverlap": "shiftY"},
        "data": data,
    }


def _today(today: dt.date, palette: Palette) -> dict[str, Any]:
    return {
        "silent": True,
        "symbol": "none",
        "animation": False,
        "label": {
            "show": True,
            "formatter": "today",
            "position": "insideEndTop",
            "color": palette.text_3,
            "fontSize": 11,
        },
        "lineStyle": {"color": palette.text_3, "type": "dashed", "width": 1},
        "data": [{"xAxis": today.isoformat()}],
    }


def _options(
    series: list[dict[str, Any]],
    legend: Sequence[str],
    palette: Palette,
    currency_format: CurrencyFormat,
    *,
    tooltip: str,
    from_zero: bool = False,
) -> dict[str, Any]:
    axis_label = {"color": palette.text_3, "fontSize": 11, "fontFamily": "Inter, system-ui"}
    return {
        "animationDuration": 500,
        # A slider redraws the chart many times a second: the lines follow it, they do not lag
        "animationDurationUpdate": 120,
        "textStyle": {"fontFamily": "Inter, system-ui, sans-serif"},
        "grid": {"left": 4, "right": 64, "top": 34, "bottom": 4, "containLabel": True},
        "legend": {
            "show": True,
            "data": list(legend),
            "top": 0,
            "left": 0,
            "icon": "roundRect",
            "itemWidth": 14,
            "itemHeight": 3,
            "itemGap": 16,
            "selectedMode": False,
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
            "axisPointer": {
                "type": "line",
                "lineStyle": {"color": palette.text_3, "width": 1, "type": "solid"},
            },
            ":formatter": tooltip,
        },
        "xAxis": {
            "type": "time",
            "boundaryGap": False,
            "axisLine": {"show": False},
            "axisTick": {"show": False},
            "splitLine": {"show": False},
            "axisLabel": {**axis_label, "hideOverlap": True},
        },
        "yAxis": {
            "type": "value",
            "scale": not from_zero,
            "axisLine": {"show": False},
            "axisTick": {"show": False},
            "splitNumber": 4,
            "splitLine": {"show": True, "lineStyle": {"color": palette.hair, "width": 1}},
            "axisLabel": {**axis_label, ":formatter": compact_js(currency_format)},
        },
        "series": series,
    }


def worth_options(
    days: Sequence[dt.date],
    *,
    so_far: Values,
    plan: Values,
    measured: Values,
    low: Values,
    high: Values,
    today: dt.date,
    compare: bool,
    palette: Palette,
    currency_format: CurrencyFormat,
) -> dict[str, Any]:
    """Net worth so far and ahead. `compare` draws the plan of what was measured too."""

    def line(name: str, color: str, values: Values, **how: bool) -> dict[str, Any]:
        return _line(
            name,
            color,
            _data(days, values),
            palette=palette,
            currency_format=currency_format,
            **how,
        )

    def band(series_id: str, values: Values, opacity: float) -> dict[str, Any]:
        return {
            "type": "line",
            "id": series_id,
            "name": "",
            "stack": "range",
            "stackStrategy": "all",
            "silent": True,
            "symbol": "none",
            "lineStyle": {"opacity": 0},
            "areaStyle": {"color": palette.accent[0], "opacity": opacity},
            "emphasis": {"disabled": True},
            "data": _data(days, values),
        }

    width = [
        None if bottom is None or top is None else top - bottom
        for bottom, top in zip(low, high, strict=True)
    ]
    past = line(SO_FAR, palette.text_2, so_far)
    past["markLine"] = _today(today, palette)
    return _options(
        [
            past,
            band(LOW_ID, low, 0),
            band(WIDTH_ID, width, _BAND_OPACITY),
            # The plan is named first in the tooltip and drawn over what was measured
            line(PLAN, palette.accent[0], plan, end_label=True) | {"z": 3},
            line(MEASURED, palette.text_3, measured, dashed=True, visible=compare, end_label=True),
        ],
        [SO_FAR, PLAN, *([MEASURED] if compare else [])],
        palette,
        currency_format,
        tooltip=_tooltip_js(
            currency_format, palette, skip=[] if compare else [MEASURED], total=False
        ),
    )


def types_options(
    days: Sequence[dt.date],
    buckets: Sequence[tuple[str, str, Values]],
    *,
    today: dt.date,
    palette: Palette,
    currency_format: CurrencyFormat,
) -> dict[str, Any]:
    """The plan by bucket (`buckets`: title, colour, values), stacked in that order."""
    series: list[dict[str, Any]] = []
    for name, color, values in buckets:
        item = _line(
            name, color, _data(days, values), palette=palette, currency_format=currency_format
        )
        item.update(
            stack="types",
            stackStrategy="all",
            areaStyle={"color": color, "opacity": _STACK_OPACITY},
        )
        series.append(item)
    if series:
        series[0]["markLine"] = _today(today, palette)
    return _options(
        series,
        [name for name, _, _ in buckets],
        palette,
        currency_format,
        tooltip=_tooltip_js(currency_format, palette, skip=[], total=True),
        from_zero=True,
    )


def goal_options(
    days: Sequence[dt.date],
    *,
    so_far: Values,
    plan: Values,
    measured: Values,
    target: int,
    today: dt.date,
    compare: bool,
    palette: Palette,
    currency_format: CurrencyFormat,
) -> dict[str, Any]:
    """What the goal held and where the plan takes it, with its target as a line across."""

    def line(name: str, color: str, values: Values, **how: bool) -> dict[str, Any]:
        return _line(
            name,
            color,
            _data(days, values),
            palette=palette,
            currency_format=currency_format,
            **how,
        )

    past = line(SO_FAR, palette.text_2, so_far)
    past["markLine"] = _today(today, palette)
    ahead = line(PLAN, palette.accent[0], plan, end_label=True) | {"z": 3}
    ahead["markLine"] = {
        "silent": True,
        "symbol": "none",
        "animation": False,
        "label": {
            "show": True,
            "position": "insideStartTop",
            "color": palette.text_2,
            "fontSize": 11,
            ":formatter": f"(p) => 'target ' + ({compact_js(currency_format)})(p.value)",
        },
        "lineStyle": {"color": palette.text_2, "type": "solid", "width": 1},
        "data": [{"yAxis": target / 1000}],
    }
    options = _options(
        [
            past,
            ahead,
            line(MEASURED, palette.text_3, measured, dashed=True, visible=compare),
        ],
        [SO_FAR, PLAN, *([MEASURED] if compare else [])],
        palette,
        currency_format,
        tooltip=_tooltip_js(
            currency_format, palette, skip=[] if compare else [MEASURED], total=False
        ),
    )
    # The target is a line, not a point: the axis would not reach it on its own
    options["yAxis"][":max"] = f"(v) => Math.max(v.max, {target / 1000 * 1.05})"
    return options
