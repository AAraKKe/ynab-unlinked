"""An advisory lock on a file, so two processes (the CLI and the app) take turns."""

from __future__ import annotations

import os
import sys
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def file_lock(path: Path) -> Generator[None]:
    """Hold an exclusive lock on `path` (created empty, for the user only) during the block.

    Waits for another process holding it. Advisory: only code taking the same lock waits.
    """
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        if sys.platform == "win32":
            import msvcrt

            while True:
                try:
                    # Locks the first byte; LK_LOCK gives up after ten tries, so try again
                    msvcrt.locking(fd, msvcrt.LK_LOCK, 1)
                    break
                except OSError:
                    continue
            try:
                yield
            finally:
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(fd, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)
