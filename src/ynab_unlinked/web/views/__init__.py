"""The app's views. Each module registers itself with `@shell.view` when imported."""

from __future__ import annotations

import importlib

_VIEW_MODULES = ("home.view", "import_.view", "networth.view", "reconcile.view", "settings")


def register() -> None:
    """Import every view module so the shell knows about it."""
    for module in _VIEW_MODULES:
        importlib.import_module(f"{__name__}.{module}")
