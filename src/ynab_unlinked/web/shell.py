"""The layout every page renders in, and the helpers views use from it.

The app is a single page: `root()` draws the sidebar, the top bar and the drop overlay once per
browser tab, and `ui.sub_pages` swaps the content column when the path changes. Views register
themselves with `@view(...)`; the shell lists them in the sidebar and routes to them.

    @shell.view("/reconcile", key="reconcile", title="Reconcile",
                subtitle="Lock what the bank confirmed", icon="reconcile", order=30)
    async def reconcile() -> None:
        ...  # rendered inside the content column, under the top bar

Files dropped anywhere on the window are handed to the Import view: either straight to the
handler it registered with `on_drop()` while it is on screen, or through `pending_uploads()`
after the shell navigates to `/import`.
"""

from __future__ import annotations

import datetime as dt
import inspect
from collections.abc import Awaitable, Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Literal

from fastapi.responses import RedirectResponse
from nicegui import PageArguments, app, context, ui
from nicegui.client import Client
from nicegui.elements.upload_files import FileUpload
from nicegui.events import MultiUploadEventArguments

from ynab_unlinked.__about__ import __version__
from ynab_unlinked.config import LatestConfig
from ynab_unlinked.store import SyncResult
from ynab_unlinked.web import theme
from ynab_unlinked.web.components import (
    button,
    clickable,
    dialog_box,
    icon,
    run_dialog,
    set_class,
    spinner,
)
from ynab_unlinked.web.state import state
from ynab_unlinked.web.wording import plural, ynab_error_message

UploadedFile = FileUpload
"""A file the browser sent. `await f.read()`, `await f.save(path)`, `f.name`, `f.size()`."""

ToastKind = Literal["ok", "info", "warn", "error"]

HOME_PATH = "/"
IMPORT_PATH = "/import"
RECONCILE_PATH = "/reconcile"
NETWORTH_PATH = "/networth"
SETTINGS_PATH = "/settings"
ONBOARDING_PATH = "/onboarding"

_SIDEBAR_KEY = "yul.sidebar"
_RAIL = "rail"
_WIDE = "wide"
_SHELL_KEY = "yul.shell"
_PENDING_KEY = "yul.pending_uploads"
_DROP_HANDLER_KEY = "yul.drop_handler"

DropHandler = Callable[[list[UploadedFile]], Awaitable[None] | None]


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
    shell = context.client.storage.get(_SHELL_KEY)
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
) -> Iterator[ui.element]:
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


@contextmanager
def edit_config(message: str | None = None) -> Iterator[LatestConfig]:
    """Change the config on disk in a block, then toast `message` (when given).

    Built on `state().edit_config()`: the file is read again first, so what the CLI saved
    meanwhile is kept, and the app state is reloaded after the save.
    """
    with state().edit_config() as config:
        yield config
    if message:
        notify(message)


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
    context.client.storage[_DROP_HANDLER_KEY] = (owner, handler)


def pending_uploads(client: Client | None = None) -> list[UploadedFile]:
    """Take the files dropped on another page of this tab. Each file is returned once."""
    storage = (client or context.client).storage
    files: list[UploadedFile] = list(storage.pop(_PENDING_KEY, None) or [])
    return files


async def hand_off_uploads(files: list[UploadedFile], client: Client | None = None) -> None:
    """Give files to the Import view: its live `on_drop` handler, or the queue and `/import`.

    What the global drop overlay does with a drop; other drop zones (Home's) call it too.
    """
    storage = (client or context.client).storage
    registered = storage.get(_DROP_HANDLER_KEY)
    if registered is not None:
        owner, handler = registered
        if not owner.is_deleted:
            result = handler(files)
            if inspect.isawaitable(result):
                await result
            return
        storage.pop(_DROP_HANDLER_KEY, None)

    storage[_PENDING_KEY] = [*(storage.get(_PENDING_KEY) or []), *files]
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


def sync_label(last: dt.datetime | None, now: dt.datetime) -> str:
    """ "synced 2 min ago" for the sync chip."""
    if last is None:
        return "not synced yet"
    seconds = max(0, int((now - last).total_seconds()))
    if seconds < 60:
        return "synced just now"
    if seconds < 3600:
        return f"synced {seconds // 60} min ago"
    if seconds < 86400:
        return f"synced {seconds // 3600} h ago"
    return f"synced {plural(seconds // 86400, 'day')} ago"


def sync_message(result: SyncResult) -> str:
    """The toast after a sync: "6 changes pulled from YNAB"."""
    count = result.transactions_changed
    if result.full:
        return f"{plural(count, 'transaction')} loaded from YNAB"
    return f"{plural(count, 'change')} pulled from YNAB"


def _sync_chip() -> None:
    with ui.element("div").classes("yul-chip click").mark("sync-chip") as chip:
        busy = spinner()
        dot = ui.element("span").classes("yul-dot")
        text = ui.label()

    def refresh() -> None:
        current = state()
        busy.set_visibility(current.syncing)
        dot.set_visibility(not current.syncing)
        set_class(dot, "warn", bool(current.sync_error))
        if current.syncing:
            text.set_text("syncing…")
        elif current.sync_error:
            text.set_text("sync failed · retry")
        else:
            text.set_text(sync_label(current.last_sync, dt.datetime.now(dt.UTC)))
        chip.props["title"] = current.sync_error or "Sync with YNAB now"

    async def sync_now() -> None:
        current = state()
        if current.syncing:
            return
        task = current.sync()
        refresh()
        busy.set_visibility(True)
        dot.set_visibility(False)
        text.set_text("syncing…")
        try:
            result = await task
        except Exception as error:
            notify(f"Sync failed. {ynab_error_message(error)}", "error")
        else:
            if result is not None:
                notify(sync_message(result))
                if result.full or result.transactions_changed:
                    refresh_view()
        refresh()

    chip.on("click", sync_now)
    refresh()
    ui.timer(5.0, refresh)


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
        _sync_chip()

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
        app.storage.user[_SIDEBAR_KEY] = _RAIL if rail else _WIDE
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
    rail = app.storage.user.get(_SIDEBAR_KEY) == _RAIL
    with ui.element("div").classes("yul-frame") as frame:
        if rail:
            frame.classes(add="rail")
        nav = _sidebar(frame)
        with ui.element("main").classes("yul-main"):
            title, subtitle = _top_bar(dark)
            shell = _Shell(title=title, subtitle=subtitle, nav=nav)
            context.client.storage[_SHELL_KEY] = shell
            with ui.element("div").classes("yul-views"):
                shell.pages = ui.sub_pages({v.path: _renderer(v) for v in views()})
    _drop_overlay()
    return None
