"""The CLI's error boundary: a failed call to YNAB is one line and exit code 1, no traceback."""

from __future__ import annotations

from typing import Any

import typer
from typer.core import TyperGroup


def ynab_error_message(error: BaseException) -> str:
    """One line for the CLI: why the call failed and what to do about it."""
    # Imported here, as in `invoke`
    from ynab_unlinked.ynab_api.errors import Failure, classify

    classified = classify(error)
    match classified.failure:
        case Failure.TIMED_OUT:
            return "YNAB did not answer in time. Check your internet connection and try again."
        case Failure.STATUS if classified.status == 401:
            return "YNAB rejected the token. Run `yul config set api_key` to enter a new one."
        case Failure.STATUS if classified.status == 429:
            return "YNAB is rate limiting this token. Try again in a few minutes."
        case Failure.STATUS:
            return f"YNAB answered {classified.status}: {classified.reason}"
        case Failure.UNREACHABLE:
            return "Could not reach YNAB. Check your internet connection and try again."
        case Failure.OTHER:
            return f"Something went wrong: {error}"


class YulGroup(TyperGroup):
    """The `yul` command group. Every subcommand runs inside `invoke`, so errors from YNAB
    or the network that reach it are reported here."""

    def invoke(self, ctx: Any) -> Any:  # the Context of the click copy Typer bundles
        # Imported here: `cli/__init__.py` builds the app with this class
        from ynab_unlinked.cli.display import error
        from ynab_unlinked.ynab_api.errors import YNAB_ERRORS

        try:
            return super().invoke(ctx)
        except YNAB_ERRORS as failure:
            error(ynab_error_message(failure))
            raise typer.Exit(1) from failure
