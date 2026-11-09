"""The charts of Cash flow and Spending, in the look of `history_chart` and `flow_chart`.

- `income_spending_options`: income and spending side by side per month; the month still
  running is faded, and a month with a label (a note in YNAB, or what stood out) carries it
  over its taller bar.
- `rate_options`: the savings rate of each complete month, with its average dashed. A chart of
  its own: a rate never shares an axis with amounts.
- `volatility_options`: one dot per category, average monthly spending across (log scale)
  and how much it moves up (steady at the bottom, spiky at the top).
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from nicegui import ui

from ynab_unlinked.config.models.v2 import CurrencyFormat
from ynab_unlinked.core.cashflow import CategoryTrend, FlowMonth
from ynab_unlinked.web.components.flow_chart import MONTH_JS
from ynab_unlinked.web.components.history_chart import compact_js, money_js
from ynab_unlinked.web.theme import Palette

FLOW_HEIGHT = 240
RATE_HEIGHT = 150
SCATTER_HEIGHT = 280
INCOME_SLOT = 0
SPENDING_SLOT = 1
LABELLED = 6
"""How many dots of the volatility chart carry their category's name."""

_TOOLTIP_CSS = (
    "border-radius:10px;padding:8px 10px;font-size:12px;min-width:150px;"
    "backdrop-filter:blur(14px);-webkit-backdrop-filter:blur(14px);"
    "box-shadow:0 10px 30px rgba(0,0,0,.3);"
)


def _tooltip(palette: Palette) -> dict[str, Any]:
    return {
        "confine": True,
        "backgroundColor": "transparent",
        "borderWidth": 0,
        "padding": 0,
        "extraCssText": (
            f"{_TOOLTIP_CSS}background:var(--surface-solid);border:1px solid var(--border-2);"
            f"color:{palette.text};"
        ),
    }


def _axis_label(palette: Palette) -> dict[str, Any]:
    return {"color": palette.text_3, "fontSize": 11, "fontFamily": "Inter, system-ui"}


def _value_axis(palette: Palette, formatter: str) -> dict[str, Any]:
    return {
        "type": "value",
        "axisLine": {"show": False},
        "axisTick": {"show": False},
        "splitNumber": 4,
        "splitLine": {"show": True, "lineStyle": {"color": palette.hair, "width": 1}},
        "axisLabel": {**_axis_label(palette), ":formatter": formatter},
    }


def _month_axis(palette: Palette, keys: Sequence[str]) -> dict[str, Any]:
    return {
        "type": "category",
        "data": list(keys),
        "axisLine": {"show": False},
        "axisTick": {"show": False},
        "axisLabel": {
            **_axis_label(palette),
            "hideOverlap": True,
            ":formatter": f"(value, index) => ({MONTH_JS})(value, index, false)",
        },
    }


def _legend(palette: Palette) -> dict[str, Any]:
    return {
        "show": True,
        "top": 0,
        "left": 0,
        "icon": "roundRect",
        "itemWidth": 10,
        "itemHeight": 10,
        "itemGap": 16,
        "textStyle": {"color": palette.text_2, "fontSize": 12},
    }


def income_spending_options(
    months: Sequence[FlowMonth], palette: Palette, currency_format: CurrencyFormat
) -> dict[str, Any]:
    keys = [month.month.strftime("%Y-%m") for month in months]

    def bars(
        name: str, color: str, values: Sequence[int], labelled: Sequence[bool]
    ) -> dict[str, Any]:
        return {
            "type": "bar",
            "name": name,
            "color": color,
            "barMaxWidth": 18,
            "barGap": "15%",
            "emphasis": {"disabled": True},
            "data": [
                {
                    "value": value / 1000,
                    "itemStyle": {
                        "borderRadius": [3, 3, 0, 0],
                        "opacity": 1 if month.complete else 0.4,
                    },
                    "label": {
                        "show": bool(month.label and labelled[index]),
                        "position": "top",
                        "formatter": month.label or "",
                        "color": palette.text_2,
                        "fontSize": 10.5,
                    },
                }
                for index, (month, value) in enumerate(zip(months, values, strict=True))
            ],
        }

    income_taller = [m.income >= m.spending for m in months]
    tooltip_js = (
        "(params) => {"
        "const ps = Array.isArray(params) ? params : [params];"
        f"const money = {money_js(currency_format)};"
        f"const title = ({MONTH_JS})(ps[0].name, 1, true);"
        "const income = ps.find((p) => p.seriesName === 'Income');"
        "const spending = ps.find((p) => p.seriesName === 'Spending');"
        "const row = (name, value) => '<div style=\"display:flex;justify-content:space-between;"
        f'gap:14px"><span style="color:{palette.text_2}">\' + name + \'</span><b style="'
        "font-variant-numeric:tabular-nums\">' + value + '</b></div>';"
        "let rows = row('Income', money(income ? income.value : 0))"
        " + row('Spending', money(spending ? spending.value : 0));"
        "if (income && spending) { const saved = income.value - spending.value;"
        " rows += row('Saved', money(saved) + (income.value > 0 ? ' · '"
        " + Math.round(saved / income.value * 100) + '%' : '')); }"
        f"return '<div style=\"color:{palette.text_3};margin-bottom:4px\">' + title + '</div>' + rows;"
        "}"
    )
    return {
        "animationDuration": 500,
        "textStyle": {"fontFamily": "Inter, system-ui, sans-serif"},
        "grid": {"left": 4, "right": 8, "top": 40, "bottom": 4, "containLabel": True},
        "legend": _legend(palette),
        "tooltip": {
            **_tooltip(palette),
            "trigger": "axis",
            "axisPointer": {"type": "shadow", "shadowStyle": {"color": palette.hair}},
            ":formatter": tooltip_js,
        },
        "xAxis": _month_axis(palette, keys),
        "yAxis": _value_axis(palette, compact_js(currency_format)),
        "series": [
            bars(
                "Income",
                palette.series[INCOME_SLOT],
                [m.income for m in months],
                income_taller,
            ),
            bars(
                "Spending",
                palette.series[SPENDING_SLOT],
                [m.spending for m in months],
                [not taller for taller in income_taller],
            ),
        ],
    }


def rate_options(
    months: Sequence[FlowMonth], palette: Palette, average: float | None
) -> dict[str, Any]:
    keys = [month.month.strftime("%Y-%m") for month in months]
    rates = [
        None if not month.complete or month.rate is None else round(month.rate * 100, 1)
        for month in months
    ]
    mark = (
        {
            "silent": True,
            "symbol": "none",
            "label": {
                "show": True,
                "position": "insideEndTop",
                "formatter": f"average {average * 100:.1f}%",
                "color": palette.text_2,
                "fontSize": 10.5,
            },
            "lineStyle": {"color": palette.text_2, "type": "dashed", "width": 1},
            "data": [{"yAxis": round(average * 100, 1)}],
        }
        if average is not None
        else None
    )
    series: dict[str, Any] = {
        "type": "line",
        "name": "Savings rate",
        "color": palette.series[INCOME_SLOT],
        "symbol": "circle",
        "symbolSize": 7,
        "connectNulls": False,
        "lineStyle": {"width": 2, "cap": "round", "join": "round"},
        "emphasis": {"disabled": True},
        "data": rates,
    }
    if mark is not None:
        series["markLine"] = mark
    return {
        "animationDuration": 500,
        "textStyle": {"fontFamily": "Inter, system-ui, sans-serif"},
        "grid": {"left": 4, "right": 8, "top": 12, "bottom": 4, "containLabel": True},
        "tooltip": {
            **_tooltip(palette),
            "trigger": "axis",
            "axisPointer": {"type": "line", "lineStyle": {"color": palette.text_3, "width": 1}},
            ":formatter": (
                "(params) => { const p = Array.isArray(params) ? params[0] : params;"
                f" return ({MONTH_JS})(p.name, 1, true) + ': '"
                " + (p.value == null ? 'still running' : p.value + '%'); }"
            ),
        },
        "xAxis": _month_axis(palette, keys),
        "yAxis": _value_axis(palette, "(v) => v + '%'"),
        "series": [series],
    }


def volatility_options(
    trends: Sequence[CategoryTrend], palette: Palette, currency_format: CurrencyFormat
) -> dict[str, Any]:
    shown = [t for t in trends if t.volatility.cv is not None and t.mean >= 1000]
    named = {t.category_id for t in sorted(shown, key=lambda t: -t.mean)[:LABELLED]}
    named |= (
        {t.category_id for t in shown if t.volatility.label == "spiky"}
        if len(named) < LABELLED
        else set()
    )
    names = [t.name for t in shown]
    return {
        "animationDuration": 500,
        "textStyle": {"fontFamily": "Inter, system-ui, sans-serif"},
        "grid": {"left": 4, "right": 28, "top": 22, "bottom": 22, "containLabel": True},
        "tooltip": {
            **_tooltip(palette),
            "trigger": "item",
            ":formatter": (
                "(p) => {"
                f"const names = {json.dumps(names)};"
                f"const money = {money_js(currency_format)};"
                "return '<b>' + names[p.dataIndex] + '</b><br>' + money(p.value[0])"
                " + ' a month · moves ' + Math.round(p.value[1] * 100) + '%';"
                "}"
            ),
        },
        "xAxis": {
            "type": "log",
            # Room for the largest category's dot and name on the right
            ":max": "(extent) => extent.max * 1.8",
            "axisLine": {"show": False},
            "axisTick": {"show": False},
            "splitLine": {"show": False},
            "axisLabel": {
                **_axis_label(palette),
                "showMaxLabel": False,
                ":formatter": compact_js(currency_format),
            },
        },
        "yAxis": {**_value_axis(palette, "(v) => Math.round(v * 100) + '%'"), "min": 0},
        "series": [
            {
                "type": "scatter",
                "symbolSize": 10,
                "color": palette.series[INCOME_SLOT],
                "itemStyle": {"borderColor": palette.hair, "borderWidth": 2},
                "emphasis": {"scale": 1.3},
                "labelLayout": {"hideOverlap": True},
                "data": [
                    {
                        "value": [
                            round(t.mean / 1000, 2),
                            round(t.volatility.cv or 0, 3),
                        ],
                        "label": {
                            "show": t.category_id in named,
                            "position": "top",
                            "distance": 6,
                            "formatter": t.name,
                            "color": palette.text_2,
                            "fontSize": 10.5,
                        },
                    }
                    for t in shown
                ],
            }
        ],
    }


DRAWER_HEIGHT = 200


def category_months_options(
    months: Sequence[str],
    spent: Sequence[int],
    palette: Palette,
    currency_format: CurrencyFormat,
    mean: float,
) -> dict[str, Any]:
    """One category's spending each month (`YYYY-MM` keys), its average dashed."""
    return {
        "animationDuration": 400,
        "textStyle": {"fontFamily": "Inter, system-ui, sans-serif"},
        "grid": {"left": 4, "right": 8, "top": 16, "bottom": 4, "containLabel": True},
        "tooltip": {
            **_tooltip(palette),
            "trigger": "axis",
            "axisPointer": {"type": "shadow", "shadowStyle": {"color": palette.hair}},
            ":formatter": (
                "(params) => { const p = Array.isArray(params) ? params[0] : params;"
                f" return ({MONTH_JS})(p.name, 1, true) + ': ' + ({money_js(currency_format)})(p.value); }}"
            ),
        },
        "xAxis": _month_axis(palette, months),
        "yAxis": _value_axis(palette, compact_js(currency_format)),
        "series": [
            {
                "type": "bar",
                "name": "Spent",
                "color": palette.series[INCOME_SLOT],
                "barMaxWidth": 16,
                "itemStyle": {"borderRadius": [3, 3, 0, 0]},
                "emphasis": {"disabled": True},
                "data": [value / 1000 for value in spent],
                "markLine": {
                    "silent": True,
                    "symbol": "none",
                    "label": {"show": False},
                    "lineStyle": {"color": palette.text_2, "type": "dashed", "width": 1},
                    "data": [{"yAxis": round(mean / 1000, 2)}],
                },
            }
        ],
    }


def histogram_options(
    bins: Sequence[tuple[int, int, int]], palette: Palette, currency_format: CurrencyFormat
) -> dict[str, Any]:
    """How many months fell in each slice (low, high, months) of a category's monthly amounts."""
    keys = [f"{low / 1000}|{high / 1000}" for low, high, _ in bins]
    slice_js = (
        f"(value) => {{ const [low, high] = String(value).split('|').map(Number);"
        f" const c = {compact_js(currency_format)}; return c(low) + '–' + c(high); }}"
    )
    return {
        "animationDuration": 400,
        "textStyle": {"fontFamily": "Inter, system-ui, sans-serif"},
        "grid": {"left": 4, "right": 8, "top": 16, "bottom": 4, "containLabel": True},
        "tooltip": {
            **_tooltip(palette),
            "trigger": "axis",
            "axisPointer": {"type": "shadow", "shadowStyle": {"color": palette.hair}},
            ":formatter": (
                "(params) => { const p = Array.isArray(params) ? params[0] : params;"
                f" return ({slice_js})(p.name) + ': ' + p.value + (p.value === 1 ? ' month' : ' months'); }}"
            ),
        },
        "xAxis": {
            "type": "category",
            "data": keys,
            "axisLine": {"show": False},
            "axisTick": {"show": False},
            "axisLabel": {**_axis_label(palette), "interval": 0, ":formatter": slice_js},
        },
        "yAxis": {**_value_axis(palette, "(v) => v"), "minInterval": 1},
        "series": [
            {
                "type": "bar",
                "name": "Months",
                "color": palette.series[4],
                "barCategoryGap": "8%",
                "itemStyle": {"borderRadius": [3, 3, 0, 0]},
                "emphasis": {"disabled": True},
                "data": [months for _, _, months in bins],
            }
        ],
    }


def chart(options: dict[str, Any], height: int) -> ui.echart:
    return ui.echart(options, renderer="svg").style(f"height:{height}px;width:100%")
