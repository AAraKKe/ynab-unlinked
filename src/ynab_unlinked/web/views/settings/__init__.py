"""Settings: connection, banks, accounts, net worth, categories, appearance and data, one module
per tab.

Every save goes through `shell.save_config`, which changes the config on disk off the event
loop, reloads the app state, and toasts.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from functools import partial

from nicegui import PageArguments, ui

from ynab_unlinked.web import shell
from ynab_unlinked.web.components import clickable, glass_card, icon, set_class
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

ICONS = {
    "Connection": "link",
    "Banks": "bank",
    "Accounts": "wallet",
    "Net worth": "networth",
    "Categories": "spending",
    "Appearance": "sun",
    "Data & privacy": "lock",
}
LEDES = {
    "Connection": "The YNAB account and the budget yul works with.",
    "Data & privacy": "What yul keeps on this computer, and how to remove it.",
}
"""One line under the title of the tabs that do not open with an explanation of their own."""


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
        # A list down the side on a wide window, a row that scrolls on a narrow one
        with ui.element("div").classes("yul-settings"):
            with ui.element("nav").classes("yul-tabs side") as tabs:
                for tab in TABS:
                    with ui.element("div").classes("yul-tab").mark(f"tab-{_slug(tab)}") as item:
                        icon(ICONS[tab], 18)
                        ui.label(tab)
                    clickable(item, partial(self.open, tab), role="tab")
                    self.tab_buttons[tab] = item
            tabs.props["role"] = "tablist"
            self.panel = glass_card().mark("settings-panel")
        await self.select(self.tab)

    async def open(self, tab: str) -> None:
        """A click on a tab: show it, and put it in the address so a reload opens it again."""
        ui.navigate.history.replace(f"{shell.SETTINGS_PATH}?tab={_slug(tab)}")
        await self.select(tab)

    async def select(self, tab: str) -> None:
        self.tab = tab
        for name, item in self.tab_buttons.items():
            set_class(item, "on", name == tab)
            item.props["aria-selected"] = "true" if name == tab else "false"
            item.update()
        # On a narrow window the tabs are a row that scrolls: keep the open one in sight
        ui.run_javascript(
            f"getHtmlElement({self.tab_buttons[tab].id})"
            "?.scrollIntoView({block: 'nearest', inline: 'nearest'})"
        )
        assert self.panel is not None
        self.panel.clear()
        with self.panel:
            ui.label(tab).classes("yul-h2").mark("settings-title")
            if lede := LEDES.get(tab):
                ui.label(lede).classes("yul-lede")
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


_KEYWORDS = {
    "Connection": "token budget ynab",
    "Banks": "import statements loaders sabadell bbva cobee",
    "Accounts": "counted closed by hand group bucket",
    "Net worth": "debt return goal balance adjustments",
    "Categories": "not spending income rules",
    "Appearance": "theme palette colours dark light",
    "Data & privacy": "copy local delete reset resync",
}
for _tab in TABS:
    shell.command(
        f"settings-{_slug(_tab)}",
        f"Settings › {_tab}",
        f"{shell.SETTINGS_PATH}?tab={_slug(_tab)}",
        icon="settings",
        keywords=_KEYWORDS.get(_tab, ""),
    )

__all__ = ["RENDERERS", "TABS", "Settings", "settings_view", "tab_from_slug"]
