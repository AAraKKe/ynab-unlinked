"""What views use from the layout every page renders in: registering, the header, toasts.

The app is a single page: `web.frame.root()` draws the sidebar, the top bar and the drop overlay
once per browser tab, and `ui.sub_pages` swaps the content column when the path changes. Views
register themselves with `@view(...)`; the frame lists them in the sidebar and routes to them.

    @shell.view("/reconcile", key="reconcile", title="Reconcile",
                subtitle="Reconcile what the bank confirmed", icon="reconcile", order=30)
    async def reconcile() -> None:
        ...  # rendered inside the content column, under the top bar

Files dropped anywhere on the window are handed to the Import view: either straight to the
handler it registered with `on_drop()` while it is on screen, or through `pending_uploads()`
after the shell navigates to `/import`.

When a sync changes the budget copy, the frame draws the page on screen again through
`refresh_view`; a view that would lose what the user set registers a gentler `on_refresh`.
"""

from __future__ import annotations

import inspect
import logging
import time
from collections.abc import Awaitable, Callable, Generator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Literal, cast

from nicegui import background_tasks, context, run, ui
from nicegui.client import Client
from nicegui.elements.upload_files import FileUpload
from nicegui.events import MultiUploadEventArguments
from nicegui.slot import Slot

from ynab_unlinked.config import LatestConfig
from ynab_unlinked.web.components import (
    button,
    dialog_box,
    icon,
    run_dialog,
    set_class,
)
from ynab_unlinked.web.palette import ACTIONS, GO_TO, Command

# Every page's path, re-exported: views navigate with `shell.<NAME>_PATH`
from ynab_unlinked.web.paths import CASHFLOW_PATH as CASHFLOW_PATH
from ynab_unlinked.web.paths import HOME_PATH as HOME_PATH
from ynab_unlinked.web.paths import IMPORT_PATH as IMPORT_PATH
from ynab_unlinked.web.paths import NETWORTH_PATH as NETWORTH_PATH
from ynab_unlinked.web.paths import ONBOARDING_PATH as ONBOARDING_PATH
from ynab_unlinked.web.paths import RECONCILE_PATH as RECONCILE_PATH
from ynab_unlinked.web.paths import SETTINGS_PATH as SETTINGS_PATH
from ynab_unlinked.web.paths import SPENDING_PATH as SPENDING_PATH
from ynab_unlinked.web.state import state
from ynab_unlinked.web.storage import tab_storage

# The words of a sync, re-exported: Settings shows them as `shell.sync_label` / `sync_message`
from ynab_unlinked.web.sync_chip import sync_label as sync_label
from ynab_unlinked.web.sync_chip import sync_message as sync_message
from ynab_unlinked.web.wording import SAVE_FAILED

logger = logging.getLogger(__name__)

UploadedFile = FileUpload
"""A file the browser sent. `await f.read()`, `await f.save(path)`, `f.name`, `f.size()`."""

ToastKind = Literal["ok", "info", "warn", "error"]
QUIET_KINDS: tuple[ToastKind, ...] = ("ok", "info")
"""Said in the top bar's status line; the others are toasts."""
STATUS_SECONDS = 4.0
TOAST_MS = 3000
LOUD_TOAST_MS = 6000
"""A warning or an error stays long enough to be read."""


LAYOUT_KEY = "yul.shell"
_PENDING_KEY = "yul.pending_uploads"
_DROP_HANDLER_KEY = "yul.drop_handler"
_REFRESH_KEY = "yul.refresh_handler"


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
    group: str | None = None
    """The sidebar heading the entry sits under ("Finances"); views of a group are adjacent
    in `order`."""

    def resolved_subtitle(self) -> str:
        return self.subtitle() if callable(self.subtitle) else self.subtitle


_VIEWS: dict[str, View] = {}
_COMMANDS: dict[str, Command] = {}


def command(
    key: str, title: str, path: str, *, icon: str, hint: str = "", keywords: str = ""
) -> None:
    """Add a place to the command palette that is not a page of its own: a tab of a view.

    Pages are in it already. A tab is found by typing, not listed before that. Registering a
    key again replaces the earlier command.
    """
    _COMMANDS[key] = Command(
        key=key,
        title=title,
        section=GO_TO,
        icon=icon,
        path=path,
        hint=hint,
        keywords=keywords,
        quiet=True,
    )


def commands() -> list[Command]:
    """What the palette knows without reading the budget: pages, their tabs, then actions."""
    pages = [
        Command(key=v.key, title=v.title, section=GO_TO, icon=v.icon, path=v.path) for v in views()
    ]
    actions = [
        Command("sync", "Sync with YNAB now", ACTIONS, "refresh", action="sync"),
        Command(
            "theme",
            "Switch between light and dark",
            ACTIONS,
            "moon",
            action="theme",
            keywords="theme appearance night day",
        ),
        Command(
            "sidebar",
            "Collapse or expand the sidebar",
            ACTIONS,
            "sidebar",
            action="sidebar",
            keywords="menu navigation rail",
        ),
    ]
    return [*pages, *_COMMANDS.values(), *actions]


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
    group: str | None = None,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Register a view: a sidebar entry and the builder for `path`.

    The builder runs inside `page(title, subtitle)`, may be async, and may take one
    `PageArguments` parameter to read the query string. `icon` is a key of
    `components.ICONS`; `bottom` puts the entry under the sidebar spacer (Settings). `live`
    views show what the store has and are rendered again after a sync from the chip; pass
    `live=False` for a view whose state the user is editing (Import, Settings). `group` puts it
    under a sidebar heading.
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
            group=group,
        )
        return builder

    return decorator


def views() -> list[View]:
    return sorted(_VIEWS.values(), key=lambda v: (v.bottom, v.order, v.key))


@dataclass
class Layout:
    """The elements of one tab's layout that views update."""

    title: ui.label
    subtitle: ui.label
    nav: dict[str, ui.element]
    badges: dict[str, ui.label]
    import_button: ui.element
    pages: ui.sub_pages | None = None
    active: str | None = None
    version: int = -1
    """The `state().data_version` the page on screen was drawn from, at the latest."""
    badges_version: int = -1
    """The one the sidebar's badges were counted from; -1 before they were."""
    status: ui.element | None = None
    """The top bar's quiet line: what `notify` says when nothing went wrong."""
    status_text: ui.label | None = None
    status_until: float = 0.0
    """When the status is put away again (`time.monotonic()`)."""


def layout() -> Layout | None:
    shell = tab_storage().get(LAYOUT_KEY)
    return shell if isinstance(shell, Layout) else None


def set_header(title: str | None = None, subtitle: str | None = None) -> None:
    """Change the top bar title or subtitle of the current tab."""
    if (shell := layout()) is None:
        return
    if title is not None:
        shell.title.set_text(title)
    if subtitle is not None:
        shell.subtitle.set_text(subtitle)


def set_active(key: str | None) -> None:
    if (shell := layout()) is None:
        return
    shell.active = key
    for nav_key, element in shell.nav.items():
        set_class(element, "on", nav_key == key)
        element.props["aria-current"] = "page" if nav_key == key else "false"
        element.update()
    # The way to Import is not offered on Import itself
    set_class(shell.import_button, "yul-gone", key == "import")


@contextmanager
def page(
    title: str | None = None, subtitle: str | None = None, *, key: str | None = None
) -> Generator[ui.element]:
    """Render a view's content inside the shell: sets the top bar, yields the content column.

    `@view` builders already run inside it; call it yourself only for content that is not a
    registered view.
    """
    set_header(title, subtitle)
    if title:
        ui.page_title(f"{title} · yul")
    set_active(key)
    with ui.element("div").classes("yul-page") as content:
        yield content


@dataclass(frozen=True)
class _Refresher:
    """How the view on screen wants to be drawn again, and the element whose lifetime it follows."""

    owner: ui.element
    handler: Callable[[], Awaitable[None] | None] | None
    automatic: bool


def on_refresh(
    owner: ui.element,
    handler: Callable[[], Awaitable[None] | None] | None = None,
    *,
    automatic: bool = True,
) -> None:
    """Say how the view is drawn again after a sync, while `owner` is on screen.

    `handler` draws it in place of the rebuild, for a view that would lose what the user set
    (a range, a filter, an open tab). `automatic=False` leaves the view alone after a sync
    nobody asked for (the copy got old, something was written): for a view the user types in.
    A sync from the chip always redraws it.
    """
    tab_storage()[_REFRESH_KEY] = _Refresher(owner, handler, automatic)


def refresh_view(*, automatic: bool = False) -> None:
    """Draw the current view again when it is `live` (a sync changed the budget copy).

    With the view's own `on_refresh` handler when it registered one, else by rebuilding it.
    `automatic` is a sync the user did not ask for.
    """
    if (shell := layout()) is None or shell.pages is None or shell.pages.is_deleted:
        return
    shell.version = state().data_version
    current = next((v for v in _VIEWS.values() if v.key == shell.active), None)
    if current is None or not current.live:
        return
    target = tab_storage().get(_REFRESH_KEY)
    if isinstance(target, _Refresher) and not target.owner.is_deleted:
        if automatic and not target.automatic:
            return
        if target.handler is not None:
            result = target.handler()
            if inspect.isawaitable(result):
                # NiceGUI returns the task as a bare `asyncio.Task`
                background_tasks.create(result, name="yul view refresh")  # pyright: ignore[reportUnknownMemberType]
            return
    shell.pages.refresh()


def _live_slot() -> Slot | None:
    """The innermost slot of the current task whose element still exists.

    A handler runs in the slot of the element that fired it. When it awaits (a save, a read)
    and the view redraws meanwhile, that element is gone, and NiceGUI can no longer tell which
    browser tab the handler belongs to. An outer slot (the page, the view) still can.
    """
    for slot in reversed(context.slot_stack):
        try:
            slot.parent  # noqa: B018 (raises once the element is gone)
        except RuntimeError:
            continue
        return slot
    return None


def notify(message: str, kind: ToastKind = "ok") -> None:
    """Tell the user what just happened, as loudly as it deserves.

    Something that worked (`ok`) or a note (`info`) is said in the top bar's status line for
    a few seconds: the page already shows the result, so nothing drops over it. A warning or
    an error is a toast under the top bar, centered over the content, for longer. Outside the
    shell (onboarding) everything is a toast.

    Safe after an await in a handler whose element a redraw removed in the meantime.
    """
    slot = _live_slot()
    if slot is None:  # nothing of this tab is left: it was closed
        return
    with slot:
        shown = layout()
        if kind in QUIET_KINDS and shown is not None and _say(shown, message, kind):
            return
        ui.notify(
            message,
            position="top",
            timeout=TOAST_MS if kind in QUIET_KINDS else LOUD_TOAST_MS,
            classes=f"yul-toast yul-toast--{kind}",
            group=False,
        )


def _say(shown: Layout, message: str, kind: ToastKind) -> bool:
    """Put `message` in the top bar's status line. False when the tab has none."""
    status, text = shown.status, shown.status_text
    if status is None or text is None or status.is_deleted:
        return False
    text.set_text(message)
    status.props["title"] = message
    set_class(status, "info", kind == "info")
    status.set_visibility(True)
    status.update()
    shown.status_until = time.monotonic() + STATUS_SECONDS
    return True


def hush(shown: Layout) -> None:
    """Put the status line away once its time is up (the frame calls it on a timer)."""
    status = shown.status
    if status is None or status.is_deleted or not status.visible:
        return
    if time.monotonic() >= shown.status_until:
        status.set_visibility(False)


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


def drop_overlay() -> None:
    """The window wide drop target, drawn once per tab by the frame."""
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
