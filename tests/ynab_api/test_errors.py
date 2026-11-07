import sqlite3

import pytest
from urllib3.exceptions import MaxRetryError, NewConnectionError, ReadTimeoutError
from ynab import ApiException

from ynab_unlinked.cli.cli_errors import ynab_error_message as cli_message
from ynab_unlinked.web.wording import (
    UNEXPECTED,
    YNAB_TIMED_OUT,
    YNAB_UNREACHABLE,
)
from ynab_unlinked.web.wording import ynab_error_message as web_message
from ynab_unlinked.ynab_api.errors import Classified, Failure, classify

OFFLINE = MaxRetryError(
    pool=None,  # type: ignore[arg-type]
    url="/plans",
    reason=NewConnectionError(None, "Failed to resolve 'api.ynab.com'"),  # type: ignore[arg-type]
)
TIMED_OUT = MaxRetryError(
    pool=None,  # type: ignore[arg-type]
    url="/plans",
    reason=ReadTimeoutError(None, "/plans", "Read timed out."),  # type: ignore[arg-type]
)


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        pytest.param(
            ApiException(status=500, reason="Internal Server Error"),
            Classified(Failure.STATUS, 500, "Internal Server Error"),
            id="status",
        ),
        pytest.param(TIMED_OUT, Classified(Failure.TIMED_OUT), id="timed-out"),
        pytest.param(OFFLINE, Classified(Failure.UNREACHABLE), id="offline"),
        # The SDK reports a failed TLS handshake with no status
        pytest.param(
            ApiException(status=0, reason="SSL handshake failed"),
            Classified(Failure.UNREACHABLE),
            id="tls",
        ),
        pytest.param(sqlite3.OperationalError("database is locked"), Classified(Failure.OTHER)),
        pytest.param(RuntimeError("a bug"), Classified(Failure.OTHER), id="bug"),
    ],
)
def test_classify_tells_why_a_call_failed(error: Exception, expected: Classified):
    assert classify(error) == expected


@pytest.mark.parametrize(
    ("error", "cli", "web"),
    [
        pytest.param(
            ApiException(status=401, reason="Unauthorized"),
            "YNAB rejected the token. Run `yul config set api_key` to enter a new one.",
            "YNAB rejected this token. Check that you copied all of it.",
            id="token",
        ),
        pytest.param(
            ApiException(status=429, reason="Too Many Requests"),
            "YNAB is rate limiting this token. Try again in a few minutes.",
            "YNAB is rate limiting this token. Try again in a few minutes.",
            id="rate-limited",
        ),
        pytest.param(
            ApiException(status=500, reason="Internal Server Error"),
            "YNAB answered 500: Internal Server Error",
            "YNAB answered 500: Internal Server Error",
            id="status",
        ),
        pytest.param(
            TIMED_OUT,
            "YNAB did not answer in time. Check your internet connection and try again.",
            YNAB_TIMED_OUT,
            id="timed-out",
        ),
        pytest.param(
            ApiException(status=0, reason="SSL handshake failed"),
            "Could not reach YNAB. Check your internet connection and try again.",
            YNAB_UNREACHABLE,
            id="tls",
        ),
        pytest.param(
            OFFLINE,
            "Could not reach YNAB. Check your internet connection and try again.",
            YNAB_UNREACHABLE,
            id="offline",
        ),
        pytest.param(
            sqlite3.OperationalError("database is locked"),
            "Something went wrong: database is locked",
            UNEXPECTED,
            id="not-ynab",
        ),
    ],
)
def test_the_cli_and_the_app_word_the_same_reason(error: Exception, cli: str, web: str):
    assert cli_message(error) == cli
    assert web_message(error) == web


def test_the_app_never_blames_ynab_for_an_error_of_its_own():
    assert "YNAB" not in web_message(sqlite3.OperationalError("no such table: transactions"))
