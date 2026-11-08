"""The `yul app` web UI. Needs the `web` extra (NiceGUI).

Importing this package is cheap and never imports NiceGUI, so the CLI can ask whether the
web UI is installed without paying for it. Everything else lives in the submodules.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

from ynab_unlinked.config.paths import web_storage_dir


def available() -> bool:
    """Whether the `web` extra is installed, checked without importing NiceGUI."""
    return importlib.util.find_spec("nicegui") is not None


def storage_dir() -> Path:
    """Where the web UI keeps per browser preferences (theme, sidebar) and their secret."""
    return web_storage_dir()
