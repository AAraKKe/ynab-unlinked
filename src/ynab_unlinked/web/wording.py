"""The words every view shares: counts, dates, sizes and what to say when YNAB fails.

Pure functions, no NiceGUI: views, the shell and the tests import them from here, so no view
imports another one for its wording.
"""

from __future__ import annotations

import datetime as dt
import re

from ynab import ApiException, PlanSummary

from ynab_unlinked.text import plural
from ynab_unlinked.ynab_api.errors import Failure, classify

COPY_TITLE = "Copying your budget from YNAB"
COPY_NOTE = "The first time can take a minute."
COPY_FAILED = "Could not copy your budget from YNAB. Check your connection and try again."
SAVE_FAILED = "Your settings could not be saved on this computer. Try again."
IMPORT_FAILED = "The import stopped before it finished. Check the account in YNAB, then try again."
YNAB_TIMED_OUT = "YNAB did not answer in time. Check your connection and try again."
YNAB_UNREACHABLE = "Could not reach YNAB. Check your connection and try again."
UNEXPECTED = "Something went wrong. Try again."

_NUMBER = re.compile(r"\d{4,}")


def short_date(day: dt.date, today: dt.date) -> str:
    """ "29 Oct", with the year only when it is not this one ("30 Dec 2025")."""
    text = f"{day.day} {day:%b}"
    return text if day.year == today.year else f"{text} {day.year}"


def human_size(size: int) -> str:
    """A file size: "512 B", "1.5 KB", "3.2 MB"."""
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    raise AssertionError("unreachable")


def ynab_error_message(error: BaseException) -> str:
    """What to tell the user when a call to YNAB fails (`ynab_api.errors.classify`).

    Only a failure of YNAB or the network blames YNAB; anything else is "something went wrong".
    """
    classified = classify(error)
    match classified.failure:
        case Failure.TIMED_OUT:
            return YNAB_TIMED_OUT
        case Failure.STATUS if classified.status == 401:
            return "YNAB rejected this token. Check that you copied all of it."
        case Failure.STATUS if classified.status == 429:
            return "YNAB is rate limiting this token. Try again in a few minutes."
        case Failure.STATUS:
            return f"YNAB answered {classified.status}: {classified.reason}"
        case Failure.UNREACHABLE:
            return YNAB_UNREACHABLE
        case Failure.OTHER:
            return UNEXPECTED


def copy_error_message(error: Exception) -> str:
    """What to tell the user when the first copy of the budget fails."""
    if isinstance(error, ApiException):
        return ynab_error_message(error)
    return COPY_FAILED


def copy_line(message: str) -> str:
    """A progress message of the copy in the user's words, with grouped figures."""
    message = message.replace("Saving to the local store", "Saving the copy on this computer")
    return _NUMBER.sub(lambda match: f"{int(match.group()):,}", message)


def budget_caption(budget: PlanSummary) -> str:
    """ "EUR · 6 accounts" under a budget's name: its currency and open accounts."""
    parts: list[str] = []
    if budget.currency_format is not None:
        parts.append(budget.currency_format.iso_code)
    if budget.accounts is not None:
        open_accounts = [a for a in budget.accounts if not a.closed and not a.deleted]
        parts.append(plural(len(open_accounts), "account"))
    return " · ".join(parts)
