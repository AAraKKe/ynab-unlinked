"""The progress line of the first copy of the budget."""

from __future__ import annotations

import asyncio

from nicegui import Client as NiceClient
from nicegui import ui

from ynab_unlinked.web.wording import copy_line


class LineProgress:
    """Shows the copy's progress messages on one label, from whatever thread sends them."""

    def __init__(self, label: ui.label, client: NiceClient) -> None:
        self.label = label
        self.client = client
        self.loop = asyncio.get_running_loop()

    def _show(self, message: str) -> None:
        self.loop.call_soon_threadsafe(self._apply, copy_line(message))

    def _apply(self, text: str) -> None:
        if self.label.is_deleted:
            return
        with self.client:
            self.label.set_text(text)

    def start(self, message: str) -> None:
        self._show(message)

    def done(self, message: str | None = None) -> None:
        if message:
            self._show(message)

    def info(self, message: str) -> None:
        self._show(message)

    def warn(self, message: str) -> None:
        self._show(message)
