"""What a failed call to YNAB means for the user, without any UI library."""

from __future__ import annotations

from urllib3.exceptions import HTTPError, MaxRetryError, NewConnectionError
from urllib3.exceptions import TimeoutError as RequestTimeout
from ynab import ApiException

YNAB_ERRORS: tuple[type[Exception], ...] = (ApiException, HTTPError)
"""What the SDK raises when YNAB answers with an error or cannot be reached."""


def api_status(error: ApiException) -> int | None:
    """The HTTP status YNAB answered with, `None` when the call never got an answer.

    The SDK leaves `status` and `reason` untyped; these two read them with their real types.
    """
    status = getattr(error, "status", None)
    return status if isinstance(status, int) else None


def api_reason(error: ApiException) -> str | None:
    """The HTTP reason phrase YNAB answered with, if any."""
    reason = getattr(error, "reason", None)
    return reason if isinstance(reason, str) else None


def timed_out(error: BaseException) -> bool:
    """Whether YNAB did not answer in time (`REQUEST_TIMEOUT`), after urllib3's retries too."""
    if isinstance(error, MaxRetryError) and error.reason is not None:
        error = error.reason
    # urllib3 makes a refused or unresolved connection a timeout too, for old callers
    return isinstance(error, RequestTimeout) and not isinstance(error, NewConnectionError)


def ynab_error_message(error: Exception) -> str:
    """One line for the CLI: why the call failed and what to do about it."""
    if timed_out(error):
        return "YNAB did not answer in time. Check your internet connection and try again."
    if isinstance(error, ApiException) and (status := api_status(error)):
        if status == 401:
            return "YNAB rejected the token. Run `yul config set api_key` to enter a new one."
        if status == 429:
            return "YNAB is rate limiting this token. Try again in a few minutes."
        return f"YNAB answered {status}: {api_reason(error)}"
    # The SDK reports a failed TLS handshake as an ApiException with no status
    return "Could not reach YNAB. Check your internet connection and try again."
