"""Controls the Reconcile view needs that `components` does not offer yet.

A pill group (one choice out of a few, like the date scope) and a switch, both drawn like the
mock rather than with Quasar's widgets. Their classes (`yul-pills`, `yul-rec-switch`) live in
`static/yul.css`. They are generic: promote them to `components` when another view needs them.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable, Mapping
from typing import Any

from nicegui import ui


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
            if name == key:
                element.classes(add="on")
            else:
                element.classes(remove="on")
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
        if current["on"]:
            element.classes(add="on")
        else:
            element.classes(remove="on")
        element.props["aria-checked"] = "true" if current["on"] else "false"
        element.update()

    async def toggle() -> None:
        current["on"] = not current["on"]
        show()
        if (pending := _call(on_change, current["on"])) is not None:
            await pending

    element.props["role"] = "switch"
    element.props["tabindex"] = "0"
    element.on("click", toggle)
    element.on("keydown.space.prevent", toggle)
    element.on("keydown.enter", toggle)
    show()
    return element


__all__ = ["pill_group", "switch"]
