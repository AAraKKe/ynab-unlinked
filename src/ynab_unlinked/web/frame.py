"""The layout of the app: the sidebar, the top bar and the content column of each browser tab.

`root()` draws them once per tab, and a `ui.sub_pages` swaps the content column when the path
changes. The views come from `shell`'s registry; what a view needs from the layout while it is
on screen is `shell`'s too (`set_header`, `notify`, `refresh_view`).

Every couple of seconds each tab looks at the app state (`_tick`): it starts a sync when the
budget copy got old, and when a sync changed the copy it updates the sidebar's badges and has
the shell draw the page on screen again.
"""

from __future__ import annotations

import datetime as dt
import inspect
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from fastapi.responses import RedirectResponse
from nicegui import PageArguments, run, ui

from ynab_unlinked.__about__ import __version__
from ynab_unlinked.web import attention, shell, theme
from ynab_unlinked.web.components import button, clickable, empty_state, icon, set_class
from ynab_unlinked.web.palette_dialog import PaletteDialog
from ynab_unlinked.web.shell import Layout, View
from ynab_unlinked.web.state import state
from ynab_unlinked.web.storage import tab_storage, user_storage
from ynab_unlinked.web.sync_chip import sync_chip

logger = logging.getLogger(__name__)

_SIDEBAR_KEY = "yul.sidebar"
_RAIL = "rail"
_WIDE = "wide"

TICK_SECONDS = 2.0
"""How often a tab looks for a sync that changed the budget copy, or a copy gone old."""
PAGE_ERROR = "This page could not be drawn."
NOT_FOUND = "There is no page at this address."


# ---- top bar ------------------------------------------------------------------------------


def _search_button(open_palette: Callable[[], Awaitable[None]]) -> None:
    """Looks like a search field, opens the command palette (also ⌘K, Ctrl+K and "/")."""
    with ui.element("button").classes("yul-search").mark("open-palette") as trigger:
        icon("search", 16)
        ui.label("Search").classes("yul-search-label")
        # The key is printed by the stylesheet: ⌘K on a Mac, Ctrl K elsewhere
        ui.element("span").classes("yul-kbd yul-kbd-palette")
    trigger.props["type"] = "button"
    trigger.props["title"] = "Search pages, settings, categories and accounts"
    trigger.props["aria-label"] = "Search"
    trigger.on("click", open_palette)


@dataclass
class _TopBar:
    title: ui.label
    subtitle: ui.label
    import_button: ui.element
    toggle_theme: Callable[[], None]
    sync_now: Callable[[], Awaitable[None]]


def _top_bar(dark: ui.dark_mode, open_palette: Callable[[], Awaitable[None]]) -> _TopBar:
    config = state().config
    with ui.element("header").classes("yul-top"):
        with ui.element("div").classes("yul-top-titles"):
            title = ui.label("").classes("yul-title")
            subtitle = ui.label("").classes("yul-subtitle")
        ui.element("span").classes("yul-grow")
        _search_button(open_palette)
        if config is not None:
            with (
                ui.element("div")
                .classes("yul-chip click yul-budget-chip")
                .mark("budget-chip") as chip
            ):
                ui.element("span").classes("yul-dot")
                ui.label(config.budget.name)
            chip.props["title"] = "Your budget. Change it in Settings"
            clickable(
                chip, lambda: ui.navigate.to(f"{shell.SETTINGS_PATH}?tab=connection"), role="link"
            )
        sync_now = sync_chip(shell.notify, shell.refresh_view)

        def toggle_theme() -> None:
            dark.value = not dark.value
            theme.save_theme(bool(dark.value))
            theme_button.clear()
            with theme_button:
                icon("sun" if dark.value else "moon", 16)

        theme_button = button(
            icon_name="sun" if dark.value else "moon", on_click=toggle_theme
        ).mark("theme-toggle")
        theme_button.props["title"] = "Theme"
        theme_button.props["aria-label"] = "Switch between light and dark"
        import_button = button(
            "Import", kind="primary", small=True, on_click=lambda: ui.navigate.to(shell.IMPORT_PATH)
        ).mark("top-import")
        import_button.classes(add="yul-top-import")
    return _TopBar(title, subtitle, import_button, toggle_theme, sync_now)


# ---- sidebar ------------------------------------------------------------------------------


def _nav_item(v: View) -> tuple[ui.element, ui.label]:
    with ui.element("a").classes("yul-nav").mark(f"nav-{v.key}") as item:
        icon(v.icon)
        ui.label(v.title).classes("yul-nav-label")
        badge = ui.label("").classes("yul-nav-badge").mark(f"nav-badge-{v.key}")
        badge.set_visibility(False)
    item.props["title"] = v.title
    return clickable(item, lambda: ui.navigate.to(v.path), role="link"), badge


def _toggle_sidebar(frame: ui.element) -> None:
    rail = "rail" not in frame.classes
    set_class(frame, "rail", rail)
    user_storage()[_SIDEBAR_KEY] = _RAIL if rail else _WIDE


def _collapse_item(frame: ui.element) -> None:
    """The sidebar's last entry: narrows it to a rail of icons, and widens it back."""
    with ui.element("div").classes("yul-nav collapse").mark("sidebar-toggle") as item:
        icon("sidebar")
        ui.label("Collapse").classes("yul-nav-label")

    def refresh() -> None:
        item.props["title"] = (
            "Expand the sidebar" if "rail" in frame.classes else "Collapse the sidebar"
        )

    def toggle() -> None:
        _toggle_sidebar(frame)
        refresh()

    clickable(item, toggle)
    refresh()


def _sidebar(frame: ui.element) -> tuple[dict[str, ui.element], dict[str, ui.label]]:
    nav: dict[str, ui.element] = {}
    badges: dict[str, ui.label] = {}
    with ui.element("aside").classes("yul-side"):
        with ui.element("div").classes("yul-brand"):
            ui.label("yul").classes("yul-mark")
            ui.label("yul").classes("yul-brand-name")
        registered = shell.views()
        group: str | None = None
        for v in (v for v in registered if not v.bottom):
            if v.group is not None and v.group != group:
                ui.label(v.group).classes("yul-nav-group").mark(f"nav-group-{v.group.lower()}")
            group = v.group
            nav[v.key], badges[v.key] = _nav_item(v)
        ui.element("div").classes("yul-side-spacer")
        for v in (v for v in registered if v.bottom):
            nav[v.key], badges[v.key] = _nav_item(v)
        _collapse_item(frame)
        ui.label(f"yul {__version__}").classes("yul-side-foot")
    return nav, badges


def _set_badge(layout: Layout, key: str, count: int, title: str) -> None:
    """Show `count` on a sidebar entry, or nothing at zero. `title` says what is counted."""
    if (badge := layout.badges.get(key)) is None or badge.is_deleted:
        return
    badge.set_text(str(count) if count else "")
    badge.set_visibility(bool(count))
    badge.props["title"] = title if count else ""
    badge.update()


async def _refresh_badges(layout: Layout) -> None:
    """Count what is waiting (to reconcile, balances gone stale) on the sidebar's entries."""
    current = state()
    if current.config is None or current.last_sync is None:
        return
    found = await run.io_bound(attention.waiting, current.store, current.config, dt.date.today())
    if found is None:  # the app is shutting down
        return
    _set_badge(layout, "reconcile", found.unreconciled, "Transactions to reconcile")
    _set_badge(layout, "networth", len(found.stale), "Balances set by hand to update")


# ---- pages and root -----------------------------------------------------------------------


class _Pages(ui.sub_pages):
    """The content column. An address without a page gets a way home, not NiceGUI's 404 line."""

    def _render_404(self) -> None:
        shell.set_header("Not found", "")
        ui.page_title("Not found · yul")
        shell.set_active(None)
        with ui.element("div").classes("yul-page"):
            empty_state(
                NOT_FOUND,
                icon_name="compass",
                action_label="Go home",
                on_action=lambda: ui.navigate.to(shell.HOME_PATH),
            ).mark("not-found")


def _page_error() -> None:
    def again() -> None:
        if (layout := shell.layout()) and layout.pages is not None:
            layout.pages.refresh()

    empty_state(PAGE_ERROR, icon_name="alert", action_label="Try again", on_action=again).mark(
        "page-error"
    )


def _renderer(v: View) -> Callable[[PageArguments], Awaitable[None]]:
    wants_arguments = bool(inspect.signature(v.builder).parameters)

    async def render(args: PageArguments) -> None:
        with shell.page(v.title, v.resolved_subtitle(), key=v.key) as content:
            try:
                result = v.builder(args) if wants_arguments else v.builder()
                if inspect.isawaitable(result):
                    await result
            except Exception:
                # One broken page must not take the app with it: say so, keep the shell
                logger.exception("The %s page could not be drawn", v.key)
                if content.is_deleted:
                    return
                content.clear()
                with content:
                    _page_error()

    return render


async def _tick(layout: Layout) -> None:
    """Keep the tab up to date: sync an old copy, follow a sync that changed it."""
    current = state()
    current.sync_if_stale()
    if current.syncing:
        return
    # Read before the copy is: a sync landing meanwhile is then seen by the next tick,
    # instead of being marked as drawn with what was read before it
    version = current.data_version
    if version != layout.badges_version:
        await _refresh_badges(layout)
        layout.badges_version = version
    if version != layout.version:
        shell.refresh_view(automatic=True)


def root() -> RedirectResponse | None:
    """Every path but `/onboarding`: the shell around the view registered for the path."""
    if not state().configured:
        return RedirectResponse(shell.ONBOARDING_PATH)

    dark = theme.page_setup()
    rail = user_storage().get(_SIDEBAR_KEY) == _RAIL
    actions: dict[str, Callable[[], Any]] = {}
    palette = PaletteDialog(shell.commands, actions)
    with ui.element("div").classes("yul-frame") as frame:
        if rail:
            frame.classes(add="rail")
        nav, badges = _sidebar(frame)
        with ui.element("main").classes("yul-main"):
            bar = _top_bar(dark, palette.open)
            layout = Layout(
                title=bar.title,
                subtitle=bar.subtitle,
                nav=nav,
                badges=badges,
                import_button=bar.import_button,
                # Before the page reads the copy: a sync landing while it draws redraws it
                version=state().data_version,
            )
            tab_storage()[shell.LAYOUT_KEY] = layout
            with ui.element("div").classes("yul-views"):
                layout.pages = _Pages({v.path: _renderer(v) for v in shell.views()})
        # Once right away for the badges, then to follow the syncs
        ui.timer(0, lambda: _tick(layout), once=True)
        ui.timer(TICK_SECONDS, lambda: _tick(layout))
    actions |= {
        "sync": bar.sync_now,
        "theme": bar.toggle_theme,
        "sidebar": lambda: _toggle_sidebar(frame),
    }
    ui.on("yul-palette", palette.open)
    shell.drop_overlay()
    return None
