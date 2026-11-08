"""Settings › Appearance: the palettes as cards with a preview; a click applies and saves one.

The choice belongs to this browser, like dark and light, so it is not in the settings file
and needs no toast: the page changes under the click.
"""

from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

from nicegui import ui

from ynab_unlinked.web import theme
from ynab_unlinked.web.components import clickable, glass_card, pill, set_class

if TYPE_CHECKING:
    from ynab_unlinked.web.views.settings import Settings


def render(page: Settings) -> None:
    ui.label(
        "How yul looks in this browser. Every palette has a dark and a light side; the switch "
        "in the top bar picks between them."
    ).classes("yul-muted").style("margin-bottom:14px")
    chosen = theme.current_theme()
    cards: dict[str, ui.element] = {}

    def pick(picked: theme.Theme) -> None:
        theme.save_theme_choice(picked)
        theme.apply_theme(picked)
        for name, card in cards.items():
            set_class(card, "live", name == picked.name)
            card.props["aria-checked"] = "true" if name == picked.name else "false"

    with ui.element("div").classes("yul-pv-grid yul-stagger").mark("themes") as grid:
        grid.props["role"] = "radiogroup"
        grid.props["aria-label"] = "Palette"
        for option in theme.THEMES.values():
            card = glass_card(hover=True).classes("yul-pv-card").mark(f"theme-{option.name}")
            with card:
                _preview(option)
                ui.label(option.title).classes("yul-bank-name")
                ui.label(option.description).classes("yul-bank-sum")
            cards[option.name] = clickable(card, partial(pick, option), role="radio")
            set_class(card, "live", option == chosen)
            card.props["aria-checked"] = "true" if option == chosen else "false"


def _preview(option: theme.Theme) -> None:
    """A small page in `option`'s palette, whatever the page's own palette is: its background
    and blobs, the primary button, an accent pill and a link."""
    with ui.element("div").classes(f"yul-pv {option.css_class}"):
        ui.label("Import").classes("yul-pv-btn")
        pill("by hand", "acc")
        ui.label("See net worth").classes("yul-pv-link")
