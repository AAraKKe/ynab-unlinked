"""The layout every page renders in, and the helpers views use from it.

The app is a single page: `root()` draws the sidebar, the top bar and the drop overlay once per
browser tab, and `ui.sub_pages` swaps the content column when the path changes. Views register
themselves with `@view(...)`; the shell lists them in the sidebar and routes to them.

    @shell.view("/reconcile", key="reconcile", title="Reconcile",
                subtitle="Reconcile what the bank confirmed", icon="reconcile", order=30)
    async def reconcile() -> None:
        ...  # rendered inside the content column, under the top bar

Files dropped anywhere on the window are handed to the Import view: either straight to the
handler it registered with `on_drop()` while it is on screen, or through `pending_uploads()`
after the shell navigates to `/import`.
"""

from __future__ import annotations

import inspect
import logging
from collections.abc import Awaitable, Callable, Generator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Literal, cast

from fastapi.responses import RedirectResponse
from nicegui import PageArguments, run, ui
from nicegui.client import Client
from nicegui.elements.upload_files import FileUpload
from nicegui.events import MultiUploadEventArguments

from ynab_unlinked.__about__ import __version__
from ynab_unlinked.config import LatestConfig
from ynab_unlinked.web import theme
from ynab_unlinked.web.components import (
    button,
    clickable,
    dialog_box,
    icon,
    run_dialog,
    set_class,
)

# Every page's path, re-exported: views navigate with `shell.<NAME>_PATH`
from ynab_unlinked.web.paths import HOME_PATH as HOME_PATH
from ynab_unlinked.web.paths import IMPORT_PATH as IMPORT_PATH
from ynab_unlinked.web.paths import NETWORTH_PATH as NETWORTH_PATH
from ynab_unlinked.web.paths import ONBOARDING_PATH as ONBOARDING_PATH
from ynab_unlinked.web.paths import RECONCILE_PATH as RECONCILE_PATH
from ynab_unlinked.web.paths import SETTINGS_PATH as SETTINGS_PATH
from ynab_unlinked.web.state import state
from ynab_unlinked.web.storage import tab_storage, user_storage

# The words of a sync, re-exported: Settings shows them as `shell.sync_label` / `sync_message`
from ynab_unlinked.web.sync_chip import sync_chip
from ynab_unlinked.web.sync_chip import sync_label as sync_label
from ynab_unlinked.web.sync_chip import sync_message as sync_message
from ynab_unlinked.web.wording import SAVE_FAILED

logger = logging.getLogger(__name__)

UploadedFile = FileUpload
"""A file the browser sent. `await f.read()`, `await f.save(path)`, `f.name`, `f.size()`."""

ToastKind = Literal["ok", "info", "warn", "error"]


_SIDEBAR_KEY = "yul.sidebar"
_RAIL = "rail"
_WIDE = "wide"
_SHELL_KEY = "yul.shell"
_PENDING_KEY = "yul.pending_uploads"
_DROP_HANDLER_KEY = "yul.drop_handler"

DropHandler = Callable[[list[UploadedFile]], Awaitable[None] | None]


@dataclass(frozen=True)
class _DropTarget:
    """The live drop handler of a tab, and the element whose lifetime it follows."""

    owner: ui.element
    handler: DropHandler


def _queued(files: object) -> list[UploadedFile]:
    """The files queued under `_PENDING_KEY`: only `hand_off_uploads` writes that list."""
    return list(cast(list[UploadedFile], files)) if files else []


@dataclass(frozen=True)
class View:
    path: str
    key: str
    title: str
    subtitle: str | Callable[[], str]
    icon: str
    order: int
    bottom: bool
    live: bool
    """Shows the store: re-rendered after a sync from the chip. False for views with forms."""
    builder: Callable[..., Any]

    def resolved_subtitle(self) -> str:
        return self.subtitle() if callable(self.subtitle) else self.subtitle


_VIEWS: dict[str, View] = {}


def view(
    path: str,
    *,
    key: str,
    title: str,
    subtitle: str | Callable[[], str] = "",
    icon: str = "sparkle",
    order: int = 50,
    bottom: bool = False,
    live: bool = True,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Register a view: a sidebar entry and the builder for `path`.

    The builder runs inside `page(title, subtitle)`, may be async, and may take one
    `PageArguments` parameter to read the query string. `icon` is a key of
    `components.ICONS`; `bottom` puts the entry under the sidebar spacer (Settings). `live`
    views show what the store has and are rendered again after a sync from the chip; pass
    `live=False` for a view whose state the user is editing (Import, Settings).
    Registering a path again replaces the earlier view.
    """

    def decorator(builder: Callable[..., Any]) -> Callable[..., Any]:
        _VIEWS[path] = View(
            path=path,
            key=key,
            title=title,
            subtitle=subtitle,
            icon=icon,
            order=order,
            bottom=bottom,
            live=live,
            builder=builder,
        )
        return builder

    return decorator


def views() -> list[View]:
    return sorted(_VIEWS.values(), key=lambda v: (v.bottom, v.order, v.key))


@dataclass
class _Shell:
    """The elements of one tab's layout that views update."""

    title: ui.label
    subtitle: ui.label
    nav: dict[str, ui.element]
    pages: ui.sub_pages | None = None
    active: str | None = None


def _shell() -> _Shell | None:
    shell = tab_storage().get(_SHELL_KEY)
    return shell if isinstance(shell, _Shell) else None


def set_header(title: str | None = None, subtitle: str | None = None) -> None:
    """Change the top bar title or subtitle of the current tab."""
    if (shell := _shell()) is None:
        return
    if title is not None:
        shell.title.set_text(title)
    if subtitle is not None:
        shell.subtitle.set_text(subtitle)


def _set_active(key: str | None) -> None:
    if (shell := _shell()) is None:
        return
    shell.active = key
    for nav_key, element in shell.nav.items():
        set_class(element, "on", nav_key == key)


@contextmanager
def page(
    title: str | None = None, subtitle: str | None = None, *, key: str | None = None
) -> Generator[ui.element]:
    """Render a view's content inside the shell: sets the top bar, yields the content column.

    `@view` builders already run inside it; call it yourself only for content that is not a
    registered view.
    """
    set_header(title, subtitle)
    if key is not None:
        _set_active(key)
    with ui.element("div").classes("yul-page") as content:
        yield content


def refresh_view() -> None:
    """Render the current view again when it is `live` (after a sync brought changes)."""
    if (shell := _shell()) is None or shell.pages is None or shell.pages.is_deleted:
        return
    current = next((v for v in _VIEWS.values() if v.key == shell.active), None)
    if current is not None and current.live:
        shell.pages.refresh()


def notify(message: str, kind: ToastKind = "ok") -> None:
    """A toast under the top bar, centered over the content, gone after 3s."""
    ui.notify(
        message,
        position="top",
        timeout=3000,
        classes=f"yul-toast yul-toast--{kind}",
        group=False,
    )


async def save_config(change: Callable[[LatestConfig], None], message: str | None = None) -> bool:
    """Apply `change` to the config on disk off the event loop, then toast `message`.

    `state().update_config(change)` through `run.io_bound`: reading and saving the file can
    wait on the disk and the keychain, and must not freeze every open page. The file is read
    again first, so what the CLI saved meanwhile is kept, and the app state is reloaded after
    the save. No toast without a `message`.

    Returns whether it was saved. A save that fails (the disk, its permissions, the keychain)
    is logged and toasted as an error here, so callers only decide what to do next.
    """
    try:
        await run.io_bound(state().update_config, change)
    except Exception:
        logger.exception("The settings could not be saved")
        notify(SAVE_FAILED, "error")
        return False
    if message:
        notify(message)
    return True


async def confirm(
    title: str, lines: Sequence[str], action_label: str, *, danger: bool = False
) -> bool:
    """Ask once before a change: title, the list of what will happen, one primary action."""
    box = dialog_box(title)
    dialog = box.dialog
    if lines:
        with box.body, ui.element("ul").classes("yul-change-list"):
            for line in lines:
                with ui.element("li"):
                    ui.label(line)
    with box.actions:
        button("Cancel", kind="ghost", on_click=lambda: dialog.submit(False)).mark("confirm-cancel")
        button(
            action_label,
            kind="danger-primary" if danger else "primary",
            on_click=lambda: dialog.submit(True),
        ).mark("confirm-action")
    return (await run_dialog(dialog)) is True


# ---- drop handoff -------------------------------------------------------------------------


def on_drop(handler: DropHandler, owner: ui.element) -> None:
    """Receive dropped files directly while `owner` is on screen (the Import view does).

    Without a live handler, dropped files are queued for `pending_uploads()` and the shell
    navigates to `/import`.
    """
    tab_storage()[_DROP_HANDLER_KEY] = _DropTarget(owner, handler)


def pending_uploads(client: Client | None = None) -> list[UploadedFile]:
    """Take the files dropped on another page of this tab. Each file is returned once."""
    return _queued(tab_storage(client).pop(_PENDING_KEY, None))


async def hand_off_uploads(files: list[UploadedFile], client: Client | None = None) -> None:
    """Give files to the Import view: its live `on_drop` handler, or the queue and `/import`.

    What the global drop overlay does with a drop; other drop zones (Home's) call it too.
    """
    storage = tab_storage(client)
    target = storage.get(_DROP_HANDLER_KEY)
    if isinstance(target, _DropTarget):
        if not target.owner.is_deleted:
            result = target.handler(files)
            if inspect.isawaitable(result):
                await result
            return
        storage.pop(_DROP_HANDLER_KEY, None)

    storage[_PENDING_KEY] = [*_queued(storage.get(_PENDING_KEY)), *files]
    ui.navigate.to(IMPORT_PATH)


async def _handle_drop(event: MultiUploadEventArguments) -> None:
    if isinstance(event.sender, ui.upload):
        event.sender.reset()
    await hand_off_uploads(list(event.files), event.client)


def _drop_overlay() -> None:
    # `display: none` in yul.css until a drag is in progress (`body.yul-dragging`), so it never
    # takes clicks or shows up for assistive tech. Not `set_visibility(False)`: NiceGUI refuses
    # uploads to hidden elements.
    upload = ui.upload(multiple=True, auto_upload=True, on_multi_upload=_handle_drop)
    upload.classes("yul-drop-upload").props("flat hide-upload-btn").mark("drop-upload")
    upload.props["aria-hidden"] = "true"
    with ui.element("div").classes("yul-dropover"), ui.element("div").classes("yul-dropover-inner"):
        with ui.element("div").classes("yul-empty-disc"):
            icon("upload", 24)
        ui.label("Drop to import")


# ---- top bar ------------------------------------------------------------------------------


def _top_bar(dark: ui.dark_mode) -> tuple[ui.label, ui.label]:
    config = state().config
    with ui.element("header").classes("yul-top"):
        title = ui.label("").classes("yul-title")
        subtitle = ui.label("").classes("yul-subtitle")
        ui.element("span").classes("yul-grow")
        if config is not None:
            with ui.element("div").classes("yul-chip").mark("budget-chip"):
                ui.element("span").classes("yul-dot")
                ui.label(config.budget.name)
        sync_chip(notify, refresh_view)

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
        button(
            "Import", kind="primary", small=True, on_click=lambda: ui.navigate.to(IMPORT_PATH)
        ).mark("top-import")
    return title, subtitle


# ---- sidebar and root ---------------------------------------------------------------------


def _nav_item(v: View) -> ui.element:
    with ui.element("div").classes("yul-nav").mark(f"nav-{v.key}") as item:
        icon(v.icon)
        ui.label(v.title).classes("yul-nav-label")
    item.props["title"] = v.title
    return clickable(item, lambda: ui.navigate.to(v.path), role="link")


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
        rail = "rail" not in frame.classes
        set_class(frame, "rail", rail)
        user_storage()[_SIDEBAR_KEY] = _RAIL if rail else _WIDE
        refresh()

    clickable(item, toggle)
    refresh()


def _sidebar(frame: ui.element) -> dict[str, ui.element]:
    nav: dict[str, ui.element] = {}
    with ui.element("aside").classes("yul-side"):
        with ui.element("div").classes("yul-brand"):
            ui.label("yul").classes("yul-mark")
            ui.label("yul").classes("yul-brand-name")
        registered = views()
        for v in (v for v in registered if not v.bottom):
            nav[v.key] = _nav_item(v)
        ui.element("div").classes("yul-side-spacer")
        for v in (v for v in registered if v.bottom):
            nav[v.key] = _nav_item(v)
        _collapse_item(frame)
        ui.label(f"yul {__version__}").classes("yul-side-foot")
    return nav


def _renderer(v: View) -> Callable[[PageArguments], Awaitable[None]]:
    wants_arguments = bool(inspect.signature(v.builder).parameters)

    async def render(args: PageArguments) -> None:
        with page(v.title, v.resolved_subtitle(), key=v.key):
            result = v.builder(args) if wants_arguments else v.builder()
            if inspect.isawaitable(result):
                await result

    return render


def root() -> RedirectResponse | None:
    """Every path but `/onboarding`: the shell around the view registered for the path."""
    if not state().configured:
        return RedirectResponse(ONBOARDING_PATH)

    dark = theme.page_setup()
    rail = user_storage().get(_SIDEBAR_KEY) == _RAIL
    with ui.element("div").classes("yul-frame") as frame:
        if rail:
            frame.classes(add="rail")
        nav = _sidebar(frame)
        with ui.element("main").classes("yul-main"):
            title, subtitle = _top_bar(dark)
            shell = _Shell(title=title, subtitle=subtitle, nav=nav)
            tab_storage()[_SHELL_KEY] = shell
            with ui.element("div").classes("yul-views"):
                shell.pages = ui.sub_pages({v.path: _renderer(v) for v in views()})
    _drop_overlay()
    return None
