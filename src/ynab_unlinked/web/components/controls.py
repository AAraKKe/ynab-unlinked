"""Controls drawn like the mock rather than with Quasar's widgets.

A pill group (one choice out of a few: Reconcile's date scope, Net worth's ranges) and a
switch (Reconcile's "include uncleared"; cards with a switch use `ui.switch`, DESIGN rule 3).
Their classes (`yul-pills`, `yul-rec-switch`) live in `static/yul.css`.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable, Mapping
from typing import Any

from nicegui import ui

from ynab_unlinked.web.components import clickable, set_class


def _call(handler: Callable[[Any], Any], value: Any) -> Any:
    result = handler(value)
    return result if inspect.isawaitable(result) else None


def pill_group(
    options: Mapping[str, str],
    value: str,
    on_change: Callable[[str], Any],
    *,
    marker: str | None = None,
) -> ui.element:
    """Pick one of `options` (key -> label). Each pill is marked `{marker}-{key}`."""
    pills: dict[str, ui.element] = {}

    async def select(key: str) -> None:
        for name, element in pills.items():
            set_class(element, "on", name == key)
        if (pending := _call(on_change, key)) is not None:
            await pending

    with ui.element("div").classes("yul-pills") as group:
        for key, label in options.items():
            with ui.element("button") as element:
                ui.label(label)
            element.props["type"] = "button"
            if key == value:
                element.classes(add="on")
            if marker:
                element.mark(f"{marker}-{key}")
            element.on("click", lambda _, key=key: select(key))
            pills[key] = element
    group.props["role"] = "group"
    return group


def switch(label: str, value: bool, on_change: Callable[[bool], Any]) -> ui.element:
    """An on/off switch with its label on the left, toggled by click, Space or Enter."""
    current = {"on": value}

    with ui.element("div").classes("yul-rec-switch") as element:
        ui.label(label)
        ui.element("span").classes("yul-rec-sw")

    def show() -> None:
        set_class(element, "on", current["on"])
        element.props["aria-checked"] = "true" if current["on"] else "false"
        element.update()

    async def toggle() -> None:
        current["on"] = not current["on"]
        show()
        if (pending := _call(on_change, current["on"])) is not None:
            await pending

    clickable(element, toggle, role="switch")
    element.on("keydown.space.prevent", toggle)
    show()
    return element
