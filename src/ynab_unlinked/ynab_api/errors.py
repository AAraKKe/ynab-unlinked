"""Why a call to YNAB failed, without any UI library: each frontend words it on top."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

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


class Failure(Enum):
    """Why a call failed, as `classify` tells it."""

    STATUS = "status"
    """YNAB answered with an error status (`Classified.status`)."""
    TIMED_OUT = "timed out"
    """YNAB did not answer in time. It may still have applied a write."""
    UNREACHABLE = "unreachable"
    """YNAB could not be reached: offline, DNS, refused, a failed TLS handshake."""
    OTHER = "other"
    """Not a failure of YNAB or the network: a bug, a file or database error."""


@dataclass(frozen=True)
class Classified:
    failure: Failure
    status: int | None = None
    reason: str | None = None


def classify(error: BaseException) -> Classified:
    """The one place that tells why a call failed; the CLI and the web app word it."""
    if timed_out(error):
        return Classified(Failure.TIMED_OUT)
    if isinstance(error, ApiException) and (status := api_status(error)):
        return Classified(Failure.STATUS, status, api_reason(error))
    # The SDK reports a failed TLS handshake as an ApiException with no status
    if isinstance(error, YNAB_ERRORS):
        return Classified(Failure.UNREACHABLE)
    return Classified(Failure.OTHER)
