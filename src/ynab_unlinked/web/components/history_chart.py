"""The history line chart: net worth over time, by bucket or by account, or one account.

`history_options()` turns series of `core.history.Point` into an ECharts option following
DESIGN.md section 4: one value axis, 2px lines with round joins, a vertical accent gradient
under a single series, a hairline horizontal grid and no vertical one, axis text in text-3,
compact ticks (`€40K`), end labels on the right, one crosshair tooltip listing every series
and a legend only with two or more series. Colours come from a `theme.Palette`, so a chart is
rebuilt with `set_options()` when the theme changes.

Amounts reach the browser in currency units; the tick, label and tooltip formatters are
small JavaScript functions built from the budget's currency format, so the chart writes
amounts the way the rest of the app does.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, cast

from nicegui import ui

from ynab_unlinked.config.models.v2 import CurrencyFormat
from ynab_unlinked.core.history import Point
from ynab_unlinked.web.theme import Palette

CHART_HEIGHT = 320

_AREA_OPACITY = 0.35
_TOOLTIP_CSS = (
    "border-radius:10px;padding:8px 10px;font-size:12px;min-width:170px;"
    "backdrop-filter:blur(14px);-webkit-backdrop-filter:blur(14px);"
    "box-shadow:0 10px 30px rgba(0,0,0,.3);"
)


@dataclass(frozen=True)
class ChartSeries:
    name: str
    points: Sequence[Point]
    color: str


def _rgba(hex_color: str, alpha: float) -> str:
    value = hex_color.lstrip("#")
    red, green, blue = (int(value[i : i + 2], 16) for i in (0, 2, 4))
    return f"rgba({red},{green},{blue},{alpha})"


def _symbol(currency_format: CurrencyFormat) -> tuple[str, bool]:
    symbol = currency_format.currency_symbol if currency_format.display_symbol else ""
    return symbol, currency_format.symbol_first


def money_js(currency_format: CurrencyFormat, digits: int | None = None) -> str:
    """A JavaScript `(units) => text` that writes an amount like `Formatter.format_amount`,
    with `digits` decimals instead of the budget's when given."""
    symbol, first = _symbol(currency_format)
    decimals = currency_format.decimal_digits if digits is None else digits
    return (
        "(v) => {"
        f"const n = Math.abs(v).toFixed({decimals}).split('.');"
        f"const i = n[0].replace(/\\B(?=(\\d{{3}})+(?!\\d))/g, {json.dumps(currency_format.group_separator)});"
        f"const s = n.length > 1 ? i + {json.dumps(currency_format.decimal_separator)} + n[1] : i;"
        f"const body = {json.dumps(first)} ? {json.dumps(symbol)} + s : s + {json.dumps(symbol)};"
        "return (v < 0 ? '-' : '') + body;}"
    )


def compact_js(currency_format: CurrencyFormat) -> str:
    """A JavaScript `(units) => text` for ticks and end labels: `€40K`, `€1.2M`, `€950`."""
    symbol, first = _symbol(currency_format)
    return (
        "(v) => {"
        "const a = Math.abs(v);"
        "const short = (x, unit) => (x >= 10 ? x.toFixed(0) : x.toFixed(1).replace(/\\.0$/, '')) + unit;"
        "let s = a >= 1e6 ? short(a / 1e6, 'M') : a >= 1e3 ? short(a / 1e3, 'K') : Math.round(a).toString();"
        f"s = s.replace('.', {json.dumps(currency_format.decimal_separator)});"
        f"const body = {json.dumps(first)} ? {json.dumps(symbol)} + s : s + {json.dumps(symbol)};"
        "return (v < 0 ? '-' : '') + body;}"
    )


def _tooltip_js(currency_format: CurrencyFormat, palette: Palette) -> str:
    return (
        "(params) => {"
        "const ps = Array.isArray(params) ? params : [params];"
        "if (!ps.length) return '';"
        f"const money = {money_js(currency_format)};"
        "const esc = (s) => String(s).replace(/[&<>\"']/g, (c) => "
        "({'&': '&amp;', '<': '&lt;', '>': '&gt;', '\"': '&quot;', \"'\": '&#39;'})[c]);"
        "const day = new Date(ps[0].value[0]).toLocaleDateString('en-GB', "
        "{day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC'});"
        "const rows = ps.map((p) => "
        "'<div style=\"display:flex;align-items:center;justify-content:space-between;gap:14px\">'"
        f" + '<span style=\"display:inline-flex;align-items:center;gap:6px;color:{palette.text_2}\">'"
        " + '<i style=\"display:inline-block;width:10px;height:2px;border-radius:1px;background:'"
        " + p.color + '\"></i>' + esc(p.seriesName) + '</span>'"
        " + '<b style=\"font-weight:600;font-variant-numeric:tabular-nums\">' + money(p.value[1])"
        " + '</b></div>').join('');"
        f"return '<div style=\"color:{palette.text_3};margin-bottom:4px\">' + day + '</div>' + rows;"
        "}"
    )


def _end_label_js(currency_format: CurrencyFormat, with_name: bool) -> str:
    name = " + ' ' + String(p.seriesName).slice(0, 16)" if with_name else ""
    return f"(p) => ({compact_js(currency_format)})(p.value[1]){name}"


def _area(color: str, *, visible: bool) -> dict[str, Any]:
    # Always present, transparent when hidden: ECharts merges an option into the previous one
    # when the series count does not change, so a missing key would keep the old area.
    return {
        "opacity": 1 if visible else 0,
        "color": {
            "type": "linear",
            "x": 0,
            "y": 0,
            "x2": 0,
            "y2": 1,
            "colorStops": [
                {"offset": 0, "color": _rgba(color, _AREA_OPACITY)},
                {"offset": 1, "color": _rgba(color, 0)},
            ],
        },
    }


def history_options(
    series: Sequence[ChartSeries], palette: Palette, currency_format: CurrencyFormat
) -> dict[str, Any]:
    """The ECharts option for `series`. A single series gets a gradient area of its colour.

    Colours are hex (`#rrggbb`); pass `palette.accent[0]` for the net worth total.
    """
    single = len(series) == 1
    legend = len(series) >= 2
    axis_label = {"color": palette.text_3, "fontSize": 11, "fontFamily": "Inter, system-ui"}

    return {
        "animationDuration": 500,
        "textStyle": {"fontFamily": "Inter, system-ui, sans-serif"},
        "grid": {
            "left": 4,
            "right": 150 if legend else 72,
            "top": 34 if legend else 12,
            "bottom": 4,
            "containLabel": True,
        },
        "legend": {
            "show": legend,
            "top": 0,
            "left": 0,
            "icon": "roundRect",
            "itemWidth": 14,
            "itemHeight": 3,
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
            "axisPointer": {
                "type": "line",
                "lineStyle": {"color": palette.text_3, "width": 1, "type": "solid"},
            },
            ":formatter": _tooltip_js(currency_format, palette),
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
            "axisLine": {"show": False},
            "axisTick": {"show": False},
            "splitNumber": 4,
            "splitLine": {"show": True, "lineStyle": {"color": palette.hair, "width": 1}},
            "axisLabel": {**axis_label, ":formatter": compact_js(currency_format)},
        },
        "series": [
            {
                "type": "line",
                "name": item.name,
                "color": item.color,
                "showSymbol": False,
                "symbol": "circle",
                "symbolSize": 7,
                "smooth": False,
                "lineStyle": {"width": 2, "cap": "round", "join": "round"},
                "emphasis": {"disabled": True},
                "areaStyle": _area(item.color, visible=single),
                "endLabel": {
                    "show": True,
                    "color": palette.text_2,
                    "fontSize": 11.5,
                    "distance": 8,
                    ":formatter": _end_label_js(currency_format, with_name=legend),
                },
                "labelLayout": {"moveOverlap": "shiftY"},
                "data": [[point.date.isoformat(), point.value / 1000] for point in item.points],
            }
            for item in series
        ],
    }


def history_chart(
    series: Sequence[ChartSeries],
    palette: Palette,
    currency_format: CurrencyFormat,
    *,
    height: int = CHART_HEIGHT,
) -> ui.echart:
    """An ECharts line chart of `series`, `height` pixels tall and as wide as its parent."""
    return ui.echart(history_options(series, palette, currency_format), renderer="svg").style(
        f"height:{height}px;width:100%"
    )


def set_options(chart: ui.echart, options: dict[str, Any]) -> None:
    """Replace the chart's option, for a new range, grouping or theme."""
    # NiceGUI types an echart's option as a bare `dict`
    current = cast(dict[str, Any], chart.options)  # pyright: ignore[reportUnknownMemberType]
    current.clear()
    current.update(options)
    chart.update()
