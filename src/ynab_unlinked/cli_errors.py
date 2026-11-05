"""The CLI's error boundary: a failed call to YNAB is one line and exit code 1, no traceback."""

from __future__ import annotations

from typing import Any

import click
from typer.core import TyperGroup


class YulGroup(TyperGroup):
    """The `yul` command group. Every subcommand runs inside `invoke`, so errors from YNAB
    or the network that reach it are reported here."""

    def invoke(self, ctx: click.Context) -> Any:
        # Imported here: `ynab_unlinked/__init__.py` builds the app with this class
        from ynab_unlinked.display import error
        from ynab_unlinked.ynab_api.errors import YNAB_ERRORS, ynab_error_message

        try:
            return super().invoke(ctx)
        except YNAB_ERRORS as failure:
            error(ynab_error_message(failure))
            raise click.exceptions.Exit(1) from failure
