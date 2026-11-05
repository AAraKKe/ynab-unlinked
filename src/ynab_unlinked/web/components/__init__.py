"""Small building blocks shared by every view, styled by the classes in `web.theme`.

Each helper creates NiceGUI elements in the current context and returns the outer one, so it
can be used inline (`pill("by hand", "acc")`) or as a container (`with glass_card(): ...`).
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from nicegui import ui

from ynab_unlinked.config.models.v2 import CurrencyFormat
from ynab_unlinked.web.components.history_chart import money_js
from ynab_unlinked.web.theme import STATIC_ROUTE

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
    "refresh": '<path d="M21 12a9 9 0 1 1-2.6-6.4L21 8"/><path d="M21 3v5h-5"/>',
    "pencil": '<path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L8 18l-4 1 1-4z"/><path d="M14.5 5.5l3 3"/>',
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


__all__ = [
    "ICONS",
    "LOGOS_DIR",
    "bank_logo",
    "ButtonKind",
    "PillKind",
    "Segment",
    "button",
    "check",
    "count_up",
    "empty_state",
    "glass_card",
    "icon",
    "pill",
    "segmented_bar",
    "share_bar",
    "spinner",
    "stat_tile",
]
