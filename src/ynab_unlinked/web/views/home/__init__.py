"""Home: `data` reads and words what it shows (no NiceGUI), `view` draws it."""

from __future__ import annotations

from ynab_unlinked.web.views.home.data import (
    Attention,
    HomeData,
    LoaderDue,
    attention_items,
    last_import_text,
    last_imports_line,
    load_home,
    message_markup,
    relative_time,
)
from ynab_unlinked.web.views.home.view import home, spark_options
from ynab_unlinked.web.wording import short_date

__all__ = [
    "Attention",
    "HomeData",
    "LoaderDue",
    "attention_items",
    "home",
    "last_import_text",
    "last_imports_line",
    "load_home",
    "message_markup",
    "relative_time",
    "short_date",
    "spark_options",
]
