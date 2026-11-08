"""The drop zone for bank statements, shared by Home and the Import view's first step.

    dropzone(on_files)                 # wide card: disc, "Drop bank statements here", hint
    dropzone(on_files, compact=True)   # one line, for the top of a list of files

It is a Quasar uploader (multiple, auto upload) with its own header and no file list, so the
whole card opens the file picker and accepts drops. Files dragged over the window usually land
on the shell's global drop overlay instead, which hands them to the Import view as well.
"""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable

from nicegui import ui
from nicegui.elements.upload_files import FileUpload
from nicegui.events import MultiUploadEventArguments

from ynab_unlinked.web.components import icon

DEFAULT_ACCEPT = ".pdf,.xlsx,.xls,.txt,.html"
"""The suffixes the loaders read."""

FilesHandler = Callable[[list[FileUpload]], Awaitable[None] | None]


def dropzone(
    on_files: FilesHandler,
    *,
    compact: bool = False,
    accept: str | None = None,
) -> ui.element:
    """A card that takes statements by drop or by click. `on_files` gets each batch once.

    `accept` is the file picker filter (`None` means `DEFAULT_ACCEPT`); dropped files are not
    filtered, the Import view tells the user what it cannot read.
    """

    async def received(event: MultiUploadEventArguments) -> None:
        upload.reset()
        result = on_files(list(event.files))
        if inspect.isawaitable(result):
            await result

    upload = ui.upload(multiple=True, auto_upload=True, on_multi_upload=received)
    upload.props(f'flat hide-upload-btn accept="{accept or DEFAULT_ACCEPT}"')
    upload.classes("yul-drop compact" if compact else "yul-drop").mark("dropzone")

    with upload.add_slot("header"), ui.element("div").classes("yul-drop-body"):
        with ui.element("div").classes("yul-drop-disc"):
            icon("upload", 16 if compact else 20)
        if compact:
            with ui.element("div").classes("yul-row").style("gap:6px"):
                ui.label("Add more files").style("font-weight:600")
                ui.label("drop or browse").classes("yul-muted")
        else:
            ui.label("Drop bank statements here").classes("yul-drop-title")
            ui.label("or anywhere in the app · pdf, xlsx, xls, txt, html").classes("yul-muted")
        # Quasar's own file input, stretched over the card: a click opens the picker
        ui.element("q-uploader-add-trigger")
    with upload.add_slot("list"):
        pass
    return upload
