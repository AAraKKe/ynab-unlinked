"""Looking for a newer yul while the app is open, and moving to it.

One `Updates` per process, reached through `updates()`. The open tabs ask it whether a check
is `due()` (when the first page opens and every half hour after that, unless the config turns
the check off) and run it; the answer is remembered for every tab.

`update()` runs the upgrade; `restart()` then stops the server, and `app.run()` starts the
new yul in this one's place, on the same address and with the same session, so the open tabs
reload into it.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import logging

from nicegui import app, run

from ynab_unlinked.__about__ import __version__
from ynab_unlinked.core.update import (
    UpdateError,
    Upgrade,
    is_newer,
    latest_version,
    run_upgrade,
)
from ynab_unlinked.web.state import state

logger = logging.getLogger(__name__)

CHECK_EVERY = dt.timedelta(minutes=30)
"""How long the app waits before it asks PyPI again, whether or not it answered. Short, so an
open app offers a release well within the hour it came out."""


class Updates:
    def __init__(self) -> None:
        self.latest: str | None = None
        """The newest release PyPI named. None until it answered once."""
        self.failed = False
        """The last check could not reach PyPI."""
        self.updating = False
        """The upgrade is running, or ran and the app is about to restart."""
        self.restarting = False
        """`restart()` was called: `app.run()` starts the new yul once the server stopped."""
        self._attempt: dt.datetime | None = None
        self._task: asyncio.Task[str | None] | None = None

    @property
    def available(self) -> str | None:
        """The version to update to. None when the running one is the newest known."""
        if self.latest is not None and is_newer(self.latest, __version__):
            return self.latest
        return None

    async def check(self) -> str | None:
        """Ask PyPI now and return `available`. Concurrent callers share the one question.

        Never raises: a failed check is remembered in `failed` and logged.
        """
        if self._task is None or self._task.done():
            self._task = asyncio.ensure_future(self._check())
        return await asyncio.shield(self._task)

    async def _check(self) -> str | None:
        self._attempt = dt.datetime.now(dt.UTC)
        try:
            self.latest = await run.io_bound(latest_version)
        except UpdateError as error:
            logger.info("%s", error)
            self.failed = True
        else:
            self.failed = False
        return self.available

    def due(self, now: dt.datetime | None = None) -> bool:
        """Whether it is time to ask PyPI again: never asked, or `CHECK_EVERY` ago.

        Never when the config turns the check off, before yul is set up or while updating.
        """
        config = state().config
        if config is None or not config.check_for_updates or self.updating:
            return False
        if self._attempt is None:
            return True
        now = now or dt.datetime.now(dt.UTC)
        return now - self._attempt >= CHECK_EVERY

    async def update(self, upgrade: Upgrade) -> str:
        """Run the upgrade off the event loop and return the version it installed.

        `UpdateError` when it fails or brings nothing newer; the app then goes on as it was.
        """
        self.updating = True
        try:
            return await run.io_bound(run_upgrade, upgrade, __version__)
        except BaseException:
            self.updating = False
            raise

    def restart(self) -> None:
        """Stop the server; `app.run()` then becomes the yul that was just installed."""
        self.restarting = True
        app.shutdown()


_updates: Updates | None = None


def updates() -> Updates:
    """The update state shared by every tab of this process."""
    global _updates
    if _updates is None:
        _updates = Updates()
    return _updates
