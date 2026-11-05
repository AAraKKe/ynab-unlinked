"""Controls the Reconcile view needs that `components` does not offer yet.

A pill group (one choice out of a few, like the date scope) and a switch, both drawn like the
mock rather than with Quasar's widgets. Their CSS is added to the page by `add_css_once`, with
classes prefixed `yul-rec-` so they never collide with the shared stylesheet. They are generic:
promote them to `components` when another view needs them.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable, Mapping
from typing import Any

from nicegui import context, ui

CSS = """
.yul-rec-pills {
  display: inline-flex; gap: 2px; background: var(--surface); border: 1px solid var(--border);
  border-radius: 10px; padding: 3px; flex: none;
}
.yul-rec-pills > button {
  font: inherit; padding: 4px 10px; border-radius: 7px; font-size: 12.5px; color: var(--text-2);
  background: none; border: 0; cursor: pointer; transition: all .15s; white-space: nowrap;
}
.yul-rec-pills > button:hover { color: var(--text); }
.yul-rec-pills > button.on {
  background: var(--surface-2); color: var(--text); box-shadow: inset 0 0 0 1px var(--border-2);
}
.yul-rec-switch {
  display: inline-flex; align-items: center; gap: 8px; cursor: pointer; font-size: 13px;
  color: var(--text-2); user-select: none; outline: none; flex: none;
}
.yul-rec-switch:focus-visible .yul-rec-sw { box-shadow: 0 0 0 3px #6366f133; }
.yul-rec-sw {
  width: 34px; height: 20px; border-radius: 999px; background: var(--surface-2);
  border: 1px solid var(--border-2); position: relative; transition: all .2s; flex: none;
}
.yul-rec-sw::after {
  content: ""; position: absolute; top: 2px; left: 2px; width: 14px; height: 14px;
  border-radius: 50%; background: var(--text-2); transition: all .2s;
}
.yul-rec-switch.on .yul-rec-sw { background: var(--accent); border-color: transparent; }
.yul-rec-switch.on .yul-rec-sw::after { transform: translateX(14px); background: #fff; }
"""

_CSS_KEY = "yul.rec.css"


def add_css_once(name: str, css: str) -> None:
    """Add `css` to the current tab once, however many times its view is opened."""
    key = f"{_CSS_KEY}.{name}"
    if context.client.storage.get(key):
        return
    context.client.storage[key] = True
    ui.add_css(css)


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
    add_css_once("controls", CSS)
    pills: dict[str, ui.element] = {}

    async def select(key: str) -> None:
        for name, element in pills.items():
            if name == key:
                element.classes(add="on")
            else:
                element.classes(remove="on")
        if (pending := _call(on_change, key)) is not None:
            await pending

    with ui.element("div").classes("yul-rec-pills") as group:
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
    add_css_once("controls", CSS)
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


__all__ = ["CSS", "add_css_once", "pill_group", "switch"]
