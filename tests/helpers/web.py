import sys
from collections.abc import Iterator
from contextlib import contextmanager

from nicegui.testing.general import nicegui_reset_globals

TOKEN = "test-session-token"


@contextmanager
def fresh_nicegui() -> Iterator[None]:
    """NiceGUI's global reset, minus its habit of unloading our modules.

    On exit the reset drops from `sys.modules` every module that registered a page (here
    `ynab_unlinked.web.views.onboarding`) and all its parents, `ynab_unlinked` included. Later
    imports would then load a second copy of the package, and patches applied to one copy would
    miss code bound to the other.
    """
    ours = {
        name: module
        for name, module in sys.modules.items()
        if name == "ynab_unlinked" or name.startswith("ynab_unlinked.")
    }
    try:
        with nicegui_reset_globals():
            yield
    finally:
        sys.modules.update(ours)
