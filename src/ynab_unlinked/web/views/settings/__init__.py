"""Settings: connection, banks, accounts, net worth, categories, appearance and data, one module
per tab.

Every save goes through `shell.save_config`, which changes the config on disk off the event
loop, reloads the app state, and toasts.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from nicegui import PageArguments, ui

from ynab_unlinked.web import shell
from ynab_unlinked.web.components import glass_card, set_class
from ynab_unlinked.web.views.settings import (
    accounts,
    appearance,
    banks,
    categories,
    connection,
    networth,
    privacy,
)

TABS = (
    "Connection",
    "Banks",
    "Accounts",
    "Net worth",
    "Categories",
    "Appearance",
    "Data & privacy",
)
_SLUG_ALIASES = {"networth": "net-worth", "data": "data-privacy", "privacy": "data-privacy"}

TabRenderer = Callable[["Settings"], Awaitable[None] | None]
RENDERERS: dict[str, TabRenderer] = {
    "Connection": connection.render,
    "Banks": banks.render,
    "Accounts": accounts.render,
    "Net worth": networth.render,
    "Categories": categories.render,
    "Appearance": appearance.render,
    "Data & privacy": privacy.render,
}
"""Each tab's module draws it into the panel; it gets the page to rerender it."""


def _slug(tab: str) -> str:
    return tab.lower().replace(" & ", "-").replace(" ", "-")


def tab_from_slug(slug: str | None) -> str:
    """The tab a `?tab=` deep link names (`accounts`, `networth`, `privacy`, ...).

    Case insensitive; anything else opens Connection.
    """
    wanted = (slug or "").strip().lower()
    wanted = _SLUG_ALIASES.get(wanted, wanted)
    return next((tab for tab in TABS if _slug(tab) == wanted), TABS[0])


class Settings:
    """The tab row and the panel the current tab is drawn in."""

    def __init__(self, tab: str = TABS[0]) -> None:
        self.tab = tab
        self.tab_buttons: dict[str, ui.element] = {}
        self.panel: ui.element | None = None

    async def render(self) -> None:
        with ui.element("div").classes("yul-tabs"):
            for tab in TABS:
                item = ui.label(tab).classes("yul-tab").mark(f"tab-{_slug(tab)}")
                item.on("click", lambda _, tab=tab: self.select(tab))
                self.tab_buttons[tab] = item
        self.panel = glass_card().mark("settings-panel")
        await self.select(self.tab)

    async def select(self, tab: str) -> None:
        self.tab = tab
        for name, item in self.tab_buttons.items():
            set_class(item, "on", name == tab)
        assert self.panel is not None
        self.panel.clear()
        with self.panel:
            result = RENDERERS[tab](self)
            if result is not None:
                await result

    async def rerender(self) -> None:
        await self.select(self.tab)


@shell.view(
    shell.SETTINGS_PATH,
    key="settings",
    title="Settings",
    subtitle="Connection, banks, accounts, categories, appearance, privacy",
    icon="settings",
    order=90,
    bottom=True,
    live=False,
)
async def settings_view(args: PageArguments) -> None:
    await Settings(tab_from_slug(args.query_parameters.get("tab"))).render()


__all__ = ["RENDERERS", "TABS", "Settings", "settings_view", "tab_from_slug"]
