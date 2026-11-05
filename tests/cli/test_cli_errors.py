from __future__ import annotations

import datetime as dt
import uuid

import pytest
from urllib3.exceptions import MaxRetryError, NewConnectionError, ReadTimeoutError
from ynab import ApiException

from tests.helpers.types import CliRunner, LoadEntityCallback
from tests.helpers.ynab_api import YnabClientStub
from ynab_unlinked.config import update_config
from ynab_unlinked.ynab_api.errors import YNAB_ERRORS

pytestmark = pytest.mark.version("V4")

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
    ("failure", "message"),
    [
        (ApiException(status=401, reason="Unauthorized"), "YNAB rejected the token"),
        (ApiException(status=429, reason="Too Many Requests"), "YNAB is rate limiting"),
        (ApiException(status=500, reason="Internal Server Error"), "YNAB answered 500"),
        (ApiException(status=0, reason="SSL handshake failed"), "Could not reach YNAB"),
        (OFFLINE, "Could not reach YNAB"),
        (TIMED_OUT, "YNAB did not answer in time"),
    ],
    ids=["token-rejected", "rate-limited", "server-error", "tls", "offline", "timed-out"],
)
def test_a_failed_ynab_call_is_one_line_and_exit_code_1(
    yul: CliRunner, ynab_api: YnabClientStub, failure: Exception, message: str
):
    ynab_api.api("accounts").get_accounts.side_effect = failure
    ynab_api.api("transactions").get_transactions.side_effect = failure

    result = yul("reconcile")

    assert result.exit_code == 1
    assert message in result.output
    assert "Traceback" not in result.output
    assert not isinstance(result.exception, YNAB_ERRORS)


def test_errors_that_are_not_from_ynab_still_raise(yul: CliRunner, ynab_api: YnabClientStub):
    ynab_api.api("transactions").get_transactions.side_effect = RuntimeError("a bug")
    ynab_api.api("accounts").get_accounts.side_effect = RuntimeError("a bug")

    result = yul("reconcile")

    assert isinstance(result.exception, RuntimeError)


def test_a_rejected_import_is_reported_without_a_traceback(
    yul: CliRunner, ynab_api: YnabClientStub, load_entity: LoadEntityCallback, today: dt.datetime
):
    update_config(lambda saved: saved.set_entity_account("test", str(uuid.UUID(int=10))))
    load_entity(today)
    ynab_api.api("transactions").create_transaction.side_effect = ApiException(
        status=429, reason="Too Many Requests"
    )

    result = yul("load test", input="y\n")

    assert result.exit_code == 1
    assert "YNAB is rate limiting this token" in result.output
