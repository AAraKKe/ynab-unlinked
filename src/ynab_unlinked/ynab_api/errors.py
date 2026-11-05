"""What a failed call to YNAB means for the user, without any UI library."""

from __future__ import annotations

from urllib3.exceptions import HTTPError
from ynab import ApiException

YNAB_ERRORS: tuple[type[Exception], ...] = (ApiException, HTTPError)
"""What the SDK raises when YNAB answers with an error or cannot be reached."""


def ynab_error_message(error: Exception) -> str:
    """One line for the CLI: why the call failed and what to do about it."""
    if isinstance(error, ApiException) and error.status:
        if error.status == 401:
            return "YNAB rejected the token. Run `yul config set api_key` to enter a new one."
        if error.status == 429:
            return "YNAB is rate limiting this token. Try again in a few minutes."
        return f"YNAB answered {error.status}: {error.reason}"
    # The SDK reports a failed TLS handshake as an ApiException with no status
    return "Could not reach YNAB. Check your internet connection and try again."
