"""The explainer behind the "i" of Return in Movers.

A made-up account told in a few steps, Back and Next, its chart moving from one step to the
next with the charts' own transition: 1,000 grows 50%, 8,500 more is put in, and a 20% fall
leaves Return up and Growth down. The words and figures are `flows.return_story`.
"""

from __future__ import annotations

from nicegui import ui

from ynab_unlinked.config.models.v2 import CurrencyFormat
from ynab_unlinked.formatter import Formatter
from ynab_unlinked.web.components import button, dialog_box, run_dialog, stat_tile
from ynab_unlinked.web.components.flow_chart import STORY_HEIGHT, story_options
from ynab_unlinked.web.components.history_chart import set_options
from ynab_unlinked.web.theme import Palette
from ynab_unlinked.web.views.networth import flows as words
from ynab_unlinked.web.views.networth.data import signed


async def show_return_story(
    formatter: Formatter, currency_format: CurrencyFormat, palette: Palette
) -> None:
    """Open the explainer and wait until it is closed."""
    steps = words.return_story(formatter)
    labels = [step.label for step in steps]
    held = [step.held for step in steps]
    put_in = [step.put_in for step in steps]
    box = dialog_box(words.RETURN_TITLE, lede=words.RETURN_LEDE, classes="yul-story")
    box.card.mark("return-story")
    at = 0

    with box.body:
        chart = ui.echart(
            story_options(labels, held, put_in, at, palette, currency_format), renderer="svg"
        )
        chart.style(f"height:{STORY_HEIGHT}px;width:100%").mark("story-chart")
        told = ui.element("div").classes("yul-story-step")
    with box.actions:
        back = button("Back", kind="ghost", on_click=lambda: go(-1)).mark("story-back")
        ahead = button("Next", kind="primary", on_click=lambda: go(1)).mark("story-next")
        done = button("Done", kind="primary", on_click=lambda: box.dialog.submit(None))
        done.mark("story-done")

    def draw() -> None:
        step = steps[at]
        set_options(chart, story_options(labels, held, put_in, at, palette, currency_format))
        told.clear()
        with told:
            ui.label(f"{at + 1} of {len(steps)}").classes("yul-faint yul-small").mark("story-count")
            ui.label(step.text).mark("story-text")
            with ui.element("div").classes("yul-story-tiles"):
                stat_tile("Return", words.percent_text(step.rate)).mark("story-return")
                stat_tile("Growth", signed(formatter, step.growth)).mark("story-growth")
            if at == len(steps) - 1:
                ui.label(words.RETURN_END).classes("yul-muted").mark("story-end")
        last = at == len(steps) - 1
        back.set_enabled(at > 0)
        ahead.set_visibility(not last)
        done.set_visibility(last)

    def go(by: int) -> None:
        nonlocal at
        at = min(max(at + by, 0), len(steps) - 1)
        draw()

    draw()
    await run_dialog(box.dialog)
