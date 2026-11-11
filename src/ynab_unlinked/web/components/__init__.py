"""Small building blocks shared by every view, styled by the classes in `web.theme`.

Each helper creates NiceGUI elements in the current context and returns the outer one, so it
can be used inline (`pill("by hand", "acc")`) or as a container (`with glass_card(): ...`).
"""

from __future__ import annotations

import inspect
import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from nicegui import ui
from ynab import PlanSummary

from ynab_unlinked.config.models.v2 import CurrencyFormat
from ynab_unlinked.text import YNAB_TOKEN_URL
from ynab_unlinked.web.components.history_chart import money_js
from ynab_unlinked.web.theme import STATIC_ROUTE
from ynab_unlinked.web.wording import budget_caption

LOGOS_DIR = Path(__file__).resolve().parent.parent / "static" / "logos"
"""One `<loader key>.svg` per bank yul ships a logo for; others get a monogram."""

ButtonKind = Literal["default", "primary", "ghost", "danger", "danger-primary"]
PillKind = Literal["default", "ok", "warn", "acc"]

COUNT_UP_MS = 900

# Inner markup of 24x24 stroke icons (the mock's set). Use them through `icon()`.
ICONS: dict[str, str] = {
    "home": '<path d="M3 11l9-7 9 7v9a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z"/>',
    "import": '<path d="M12 3v12m0 0 4-4m-4 4-4-4"/>'
    '<path d="M4 17v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2"/>',
    "upload": '<path d="M12 16V4m0 0 4 4m-4-4-4 4"/><path d="M4 16v3a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-3"/>',
    "reconcile": '<path d="M9 12l2 2 4-4"/><circle cx="12" cy="12" r="9"/>',
    "networth": '<path d="M3 17l6-6 4 4 8-8"/><path d="M14 7h7v7"/>',
    "cashflow": '<path d="M7 4v16m0 0-3-3m3 3 3-3"/><path d="M17 20V4m0 0-3 3m3-3 3 3"/>',
    "spending": '<path d="M12 3a9 9 0 1 0 9 9h-9z"/><path d="M15 3.5A9 9 0 0 1 20.5 9H15z"/>',
    "plan": '<path d="M5 21V4"/><path d="M5 4h12l-2.5 4 2.5 4H5"/>',
    "settings": '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 '
    "2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 "
    "1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 "
    "0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 "
    "1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 "
    "0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0 "
    '-1.5 1z"/>',
    "moon": '<path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/>',
    "sun": '<circle cx="12" cy="12" r="4"/><path d="M12 2v2m0 16v2M4.9 4.9l1.4 1.4m11.4 11.4 1.4 1.4'
    'M2 12h2m16 0h2M4.9 19.1l1.4-1.4m11.4-11.4 1.4-1.4"/>',
    "sidebar": '<rect x="3" y="4" width="18" height="16" rx="3"/><path d="M9 4v16"/>',
    "sparkle": '<path d="M12 2l2.4 5 5.6.8-4 3.9.9 5.6-4.9-2.6L7.1 17.3l.9-5.6-4-3.9L9.6 7z"/>',
    "lock": '<rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/>',
    "eye": '<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "x": '<path d="M6 6l12 12M18 6 6 18"/>',
    "check": '<path d="M20 6 9 17l-5-5"/>',
    "undo": '<path d="M9 14 4 9l5-5"/><path d="M4 9h10.5a5.5 5.5 0 0 1 0 11H11"/>',
    "refresh": '<path d="M21 12a9 9 0 1 1-2.6-6.4L21 8"/><path d="M21 3v5h-5"/>',
    "chevron-down": '<path d="M6 9l6 6 6-6"/>',
    "arrow-left": '<path d="M19 12H5m0 0 6-6m-6 6 6 6"/>',
    "pencil": '<path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L8 18l-4 1 1-4z"/><path d="M14.5 5.5l3 3"/>',
    "info": '<circle cx="12" cy="12" r="9"/><path d="M12 11v5m0-8.5h.01"/>',
    "search": '<circle cx="11" cy="11" r="7"/><path d="M21 21l-4.3-4.3"/>',
    "arrow-right": '<path d="M5 12h14m0 0-6-6m6 6-6 6"/>',
    "compass": '<circle cx="12" cy="12" r="9"/><path d="M15.5 8.5l-2 5-5 2 2-5z"/>',
    "alert": '<path d="M12 9v4m0 4h.01"/><path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 '
    '1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/>',
    "link": '<path d="M10 13a5 5 0 0 0 7.1 0l2.8-2.8a5 5 0 0 0-7.1-7.1l-1.3 1.3"/>'
    '<path d="M14 11a5 5 0 0 0-7.1 0l-2.8 2.8a5 5 0 0 0 7.1 7.1l1.3-1.3"/>',
    "bank": '<path d="M3 10l9-6 9 6"/><path d="M5 10v8m4.7-8v8m4.6-8v8M19 10v8M3 21h18"/>',
    "wallet": '<path d="M4 7a2 2 0 0 1 2-2h11a2 2 0 0 1 2 2v1"/>'
    '<rect x="3" y="7" width="18" height="13" rx="2.5"/><path d="M16 13.5h2"/>',
    "calendar": '<rect x="3" y="5" width="18" height="16" rx="3"/><path d="M3 10h18M8 3v4m8-4v4"/>',
}


def icon(name: str, size: int = 20) -> ui.html:
    """One of `ICONS`, drawn with the current text colour."""
    markup = ICONS[name]
    return ui.html(
        f'<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
        f'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">{markup}</svg>',
        sanitize=False,
    ).style("display:contents")


def button(
    text: str = "",
    *,
    on_click: Callable[..., Any] | None = None,
    kind: ButtonKind = "default",
    small: bool = False,
    icon_name: str | None = None,
) -> ui.button:
    """A button in the app's style. Quasar's own colours are switched off."""
    classes = ["yul-btn"]
    match kind:
        case "primary":
            classes.append("primary")
        case "ghost":
            classes.append("ghost")
        case "danger":
            classes.append("danger")
        case "danger-primary":
            classes += ["danger", "primary"]
        case "default":
            pass
    if small:
        # Not "sm": that is a Quasar visibility class, hidden outside the small breakpoint
        classes.append("small")
    if icon_name and not text:
        classes.append("icon")

    with (
        ui.button(on_click=on_click, color=None)
        .props("no-caps unelevated :ripple=false")
        .classes(" ".join(classes)) as element
    ):
        if icon_name:
            icon(icon_name, 16)
        if text:
            ui.label(text)
    return element


def bank_logo(key: str, title: str, *, size: int = 36) -> ui.element:
    """The bank's logo on a white tile `size` px tall, or its monogram when yul ships none."""
    tile = ui.element("div").classes("yul-bank-logo").style(f"--logo-size:{size}px")
    tile.props["title"] = title
    with tile:
        if (LOGOS_DIR / f"{key}.svg").is_file():
            ui.element("img").props(f'src="{STATIC_ROUTE}/logos/{key}.svg" alt="{title}"')
        else:
            ui.label("".join(word[0] for word in title.split()[:2]).upper()).classes(
                "yul-bank-mono"
            )
    return tile


def glass_card(*, hover: bool = False, flush: bool = False) -> ui.element:
    """The translucent surface every grouped piece of content sits on."""
    element = ui.element("div").classes("yul-card")
    if hover:
        element.classes("hov")
    if flush:
        element.classes("flush")
    return element


def pill(text: str, kind: PillKind = "default") -> ui.label:
    """A small rounded tag: `ok` and `warn` carry status, `acc` marks a choice."""
    element = ui.label(text).classes("yul-pill")
    if kind != "default":
        element.classes(kind)
    return element


def closed_pill() -> ui.label:
    """The faint "closed" tag next to the name of an account closed in YNAB."""
    element = pill("closed").classes("yul-pill-closed")
    element.props["title"] = "Closed in YNAB: counted for the time it held money"
    return element


def stat_tile(
    label: str, value: str, *, hint: str | None = None, swatch: str | None = None
) -> ui.element:
    """A labelled big number, optionally with a colour swatch and a hint line under it."""
    with glass_card().classes("yul-tile") as tile:
        with ui.element("div").classes("yul-tile-l"):
            if swatch:
                ui.element("span").classes("yul-swatch").style(f"background:{swatch}")
            ui.label(label)
        ui.label(value).classes("yul-tile-v")
        if hint:
            ui.label(hint).classes("yul-tile-w")
    return tile


@dataclass(frozen=True)
class Segment:
    label: str
    value: float
    """Any non negative weight; the bar shows each segment's share of the sum."""
    color: str


def segmented_bar(segments: Sequence[Segment]) -> ui.element:
    """A thin composition bar. Segments with no weight are left out."""
    total = sum(max(segment.value, 0) for segment in segments)
    labels: list[str] = []
    with ui.element("div").classes("yul-seg") as bar:
        for segment in segments:
            if total <= 0 or segment.value <= 0:
                continue
            share = segment.value / total * 100
            labels.append(f"{segment.label} {share:.1f}%")
            part = ui.element("div").style(f"width:{share:.2f}%;background:{segment.color}")
            part.props["title"] = labels[-1]
    bar.props["role"] = "img"
    bar.props["aria-label"] = ", ".join(labels)
    return bar


def empty_state(
    message: str,
    *,
    icon_name: str = "sparkle",
    action_label: str | None = None,
    on_action: Callable[..., Any] | None = None,
) -> ui.element:
    """Gradient icon disc, one line, and at most one button."""
    with glass_card().classes("yul-empty") as element:
        with ui.element("div").classes("yul-empty-disc"):
            icon(icon_name, 24)
        ui.label(message).classes("yul-empty-text")
        if action_label:
            button(action_label, on_click=on_action, kind="primary")
    return element


def explain_button(title: str, on_click: Callable[[], Any], *, marker: str) -> ui.element:
    """The "i" of `info_button` for an explanation too long for its note: it calls `on_click`
    (which opens a dialog) instead."""
    with ui.element("button").classes("yul-info").mark(marker) as trigger:
        icon("info", 15)
    trigger.props["type"] = "button"
    trigger.props["title"] = title
    trigger.props["aria-label"] = title
    trigger.on("click", on_click)
    # A click on the "i" must not also be a click on the card or the row it sits in
    trigger.on("click.stop", lambda: None)
    return trigger


def info_button(title: str, lines: Sequence[str], *, marker: str) -> ui.element:
    """A small "i" that opens a note next to it: a title and a few short paragraphs.

    For what a figure means when that is not what the user may expect. The button is marked
    `marker`, the note `<marker>-note`.
    """
    with ui.element("button").classes("yul-info").mark(marker) as trigger:
        icon("info", 15)
        with ui.menu().classes("yul-info-note").mark(f"{marker}-note"):
            ui.label(title).classes("yul-card-title")
            for line in lines:
                ui.label(line)
    trigger.props["type"] = "button"
    trigger.props["title"] = title
    trigger.props["aria-label"] = title
    # A click on the "i" must not also be a click on the card or the row it sits in
    trigger.on("click.stop", lambda: None)
    return trigger


def token_hint() -> ui.element:
    """Where a Personal Access Token is created, with a link that opens YNAB on that page."""
    with ui.element("div").classes("yul-token-hint").mark("token-hint") as hint:
        ui.link("Create one in YNAB", YNAB_TOKEN_URL, new_tab=True).classes("yul-link")
        ui.label("under Account Settings → Developer Settings.")
    return hint


def share_bar(fraction: float, color: str) -> ui.element:
    """A 4px track filled to `fraction` (0..1) in `color`, growing in on first paint."""
    width = max(0.0, min(fraction, 1.0)) * 100
    with ui.element("div").classes("yul-nw-bar") as bar:
        ui.element("i").style(f"width:{width:.2f}%;background:{color}")
    return bar


def count_up(label: ui.label, milliunits: int, currency_format: CurrencyFormat) -> None:
    """Make a hero figure count from zero to its amount over 900ms (ease out cubic).

    The label already holds the final text, which is what it shows at the end, without
    JavaScript, and with `prefers-reduced-motion`.
    """
    target = json.dumps(milliunits / 1000)
    ui.run_javascript(
        "(() => {"
        "if (matchMedia('(prefers-reduced-motion: reduce)').matches) return;"
        f"const money = {money_js(currency_format)};"
        "let tries = 0;"
        "const start = () => {"
        f"  const el = document.getElementById('c{label.id}');"
        "  if (!el) { if (tries++ < 40) setTimeout(start, 25); return; }"
        "  const final = el.textContent; const t0 = performance.now();"
        "  const tick = (t) => {"
        f"    const p = Math.min(1, (t - t0) / {COUNT_UP_MS}); const e = 1 - Math.pow(1 - p, 3);"
        f"    el.textContent = p < 1 ? money({target} * e) : final;"
        "    if (p < 1) requestAnimationFrame(tick);"
        "  };"
        "  requestAnimationFrame(tick);"
        "};"
        "start();"
        "})()"
    )


def spinner() -> ui.element:
    return ui.element("span").classes("yul-spin")


def check(*, big: bool = False) -> ui.html:
    """An SVG check mark that draws itself."""
    return ui.html(
        f'<svg class="yul-check{" big" if big else ""}" viewBox="0 0 24 24">'
        '<circle cx="12" cy="12" r="10"/><path d="M7.5 12.5l3 3 6-6"/></svg>',
        sanitize=False,
    ).style("display:contents")


# ---- behaviour and layout helpers ------------------------------------------------------------


def set_class(element: ui.element, name: str, on: bool) -> None:
    """Add the class `name` (one or more, space separated) when `on`, remove it otherwise."""
    if on:
        element.classes(add=name)
    else:
        element.classes(remove=name)


def clickable(
    element: ui.element, handler: Callable[..., Any], *, role: str = "button"
) -> ui.element:
    """Make a plain element act on click and on Enter, reachable with Tab, with an ARIA role."""
    element.props["role"] = role
    element.props["tabindex"] = "0"
    element.on("click", handler)
    element.on("keydown.enter", handler)
    return element


def loading(text: str) -> ui.label:
    """A spinner and a muted line: "Checking with YNAB…". Returns the line."""
    spinner()
    return ui.label(text).classes("yul-muted")


StateKind = Literal["loading", "error", "ok"]


def show_state(box: ui.element, kind: StateKind, text: str) -> ui.label:
    """Replace what `box` shows with one state line: loading, an error, or a check and text."""
    box.clear()
    with box:
        match kind:
            case "loading":
                return loading(text)
            case "error":
                return ui.label(text).classes("yul-bad")
            case "ok":
                check()
                return ui.label(text).classes("yul-muted")


def section_title(text: str, *, swatch: str | None = None) -> ui.element:
    """A `yul-section` heading, with a colour swatch before the text when given."""
    with ui.element("div").classes("yul-section") as title:
        if swatch:
            ui.element("span").classes("yul-swatch").style(f"background:{swatch}")
        ui.label(text)
    return title


def card_switch(
    card: ui.element,
    *,
    on: bool,
    marker: str,
    title: str,
    on_change: Callable[[bool], Any],
    aria_label: str | None = None,
) -> ui.switch:
    """The switch in the header of a card that can be turned on (DESIGN rule 3).

    Makes the card `live` when on and `off` (muted) when off, and draws the `ui.switch`, marked
    `marker`, where it is called. `on_change` gets the new value; the switch is disabled until
    it returns (a save in flight), so a second flip cannot start a save racing the first.
    """
    card.classes(add="live" if on else "off", remove="off" if on else "live")
    switch = ui.switch(value=on).props("dense").mark(marker)
    switch.props["title"] = title
    if aria_label is not None:
        switch.props["aria-label"] = aria_label

    async def changed(value: bool) -> None:
        switch.disable()
        try:
            if inspect.isawaitable(result := on_change(value)):
                await result
        finally:
            # The handler usually draws the card again, with a new switch
            if not switch.is_deleted:
                switch.enable()

    switch.on_value_change(lambda e: changed(bool(e.value)))
    return switch


@dataclass(frozen=True)
class DialogBox:
    """The parts of a `dialog_box`: fill `body`, put Cancel and the primary in `actions`."""

    dialog: ui.dialog
    card: ui.element
    body: ui.element
    actions: ui.element


def dialog_box(
    title: str | None = None, *, lede: str | None = None, classes: str = ""
) -> DialogBox:
    """A dialog on a solid card: title, lede, a body and the actions row aligned right.

    Without a title the body draws its own head (the bank dialog has the logo in it).
    """
    with (
        ui.dialog() as dialog,
        ui.element("div").classes(f"yul-card yul-dialog {classes}".strip()) as card,
    ):
        if title is not None:
            ui.label(title).classes("yul-h2")
        if lede is not None:
            ui.label(lede).classes("yul-lede")
        body = ui.element("div")
        actions = ui.element("div").classes("yul-row").style("justify-content:flex-end")
    return DialogBox(dialog=dialog, card=card, body=body, actions=actions)


async def run_dialog(dialog: ui.dialog) -> Any:
    """Open `dialog`, wait for what it is submitted with (None when dismissed), delete it."""
    dialog.open()
    try:
        return await dialog
    finally:
        dialog.delete()


def budget_tiles(
    budgets: Sequence[PlanSummary], selected: str | None, on_pick: Callable[[PlanSummary], Any]
) -> tuple[ui.element, dict[str, ui.element]]:
    """The budgets as a grid of tiles (name and caption), the selected one `on`.

    Each tile is marked `budget-{id}`. Returns the grid and the tiles by budget id.
    """
    tiles: dict[str, ui.element] = {}
    with ui.element("div").classes("yul-optgrid") as grid:
        for budget in budgets:
            budget_id = str(budget.id)
            with ui.element("div").classes("yul-opt").mark(f"budget-{budget_id}") as tile:
                ui.label(budget.name)
                ui.label(budget_caption(budget)).classes("yul-faint yul-small")
            set_class(tile, "on", budget_id == selected)
            tile.on("click", lambda _, budget=budget: on_pick(budget))
            tiles[budget_id] = tile
    return grid, tiles


__all__ = [
    "ICONS",
    "LOGOS_DIR",
    "ButtonKind",
    "DialogBox",
    "PillKind",
    "Segment",
    "StateKind",
    "bank_logo",
    "budget_tiles",
    "button",
    "card_switch",
    "check",
    "clickable",
    "count_up",
    "dialog_box",
    "empty_state",
    "glass_card",
    "icon",
    "loading",
    "pill",
    "closed_pill",
    "run_dialog",
    "section_title",
    "segmented_bar",
    "set_class",
    "share_bar",
    "show_state",
    "spinner",
    "stat_tile",
]
