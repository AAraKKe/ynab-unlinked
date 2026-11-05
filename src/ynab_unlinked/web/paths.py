"""The path of every page. `shell` re-exports them; NiceGUI-free code (the views' data
modules) imports them from here."""

from __future__ import annotations

HOME_PATH = "/"
IMPORT_PATH = "/import"
RECONCILE_PATH = "/reconcile"
NETWORTH_PATH = "/networth"
SETTINGS_PATH = "/settings"
ONBOARDING_PATH = "/onboarding"

__all__ = [
    "HOME_PATH",
    "IMPORT_PATH",
    "NETWORTH_PATH",
    "ONBOARDING_PATH",
    "RECONCILE_PATH",
    "SETTINGS_PATH",
]
