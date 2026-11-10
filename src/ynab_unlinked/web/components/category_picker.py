"""Pick one category of the budget: a button opening a menu of groups with a search field on top.

A budget can have hundreds of categories, so the list is never laid out on the page: the menu
lists every group with its categories under it, and typing filters them at once
(`web.categories.matching`). Picking one closes the menu and calls back with its id.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable, Sequence
from functools import partial
from typing import Any

from nicegui import ui

from ynab_unlinked.web.categories import Group, matching
from ynab_unlinked.web.components import button, clickable


def category_picker(
    groups: Sequence[Group],
    on_pick: Callable[[str], Any],
    *,
    label: str,
    marker: str,
) -> ui.button:
    """The button, marked `marker`; its search field is `{marker}-search` and each category in
    the list `{marker}-{category id}`."""
    trigger = button(label, kind="ghost", small=True, icon_name="chevron-down").mark(marker)
    with trigger, ui.menu().classes("yul-catpick").props("max-height=420px") as menu:
        search = (
            ui.input(placeholder="Type to find a category")
            .props("outlined dense autofocus clearable")
            .classes("yul-catpick-search")
            .mark(f"{marker}-search")
        )
        # Typing a space in the field must not reach the menu, which would close
        search.on("keydown.space.stop", lambda: None)
        results = ui.element("div").classes("yul-catpick-list")

    async def pick(category_id: str) -> None:
        menu.close()
        result = on_pick(category_id)
        if inspect.isawaitable(result):
            await result

    def draw(text: str) -> None:
        results.clear()
        found = matching(groups, text)
        with results:
            if not found:
                ui.label("No category matches").classes("yul-faint yul-small yul-catpick-none")
            for group in found:
                ui.label(group.name).classes("yul-catpick-group")
                for category in group.categories:
                    item = ui.label(category.name).classes("yul-catpick-item")
                    clickable(item.mark(f"{marker}-{category.id}"), partial(pick, category.id))

    search.on_value_change(lambda e: draw(e.value or ""))
    draw("")
    return trigger
