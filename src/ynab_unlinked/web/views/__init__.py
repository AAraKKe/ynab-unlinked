"""The app's views. Each module registers itself with `@shell.view` when imported."""

from __future__ import annotations


def register() -> None:
    """Import every view module so the shell knows about it."""
    from . import home, import_, networth, reconcile, settings  # noqa: F401
