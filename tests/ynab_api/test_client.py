"""Every test here asserts on the call the wrapper makes to the generated YNAB API."""

import datetime as dt
import socket
import time
from collections.abc import Iterator
from uuid import UUID

import pytest
from ynab import ApiException, TransactionClearedStatus

from tests.factories import PendingImportFactory
from tests.helpers.ynab_api import YnabClientStub
from ynab_unlinked.cli.cli_errors import ynab_error_message
from ynab_unlinked.web.wording import YNAB_TIMED_OUT
from ynab_unlinked.web.wording import ynab_error_message as web_error_message
from ynab_unlinked.ynab_api import client as client_module
from ynab_unlinked.ynab_api.client import Client
from ynab_unlinked.ynab_api.errors import YNAB_ERRORS, timed_out

BUDGET_ID = "00000000-0000-0000-0000-000000000001"
ACCOUNT_ID = "00000000-0000-0000-0000-00000000000a"


@pytest.fixture
def client(ynab_api: YnabClientStub) -> Client:
    """A real client whose `api` is served by the shared stub registry."""
    return Client(api_key="an-api-key")


def test_api_rejects_an_unknown_name():
    with pytest.raises(ValueError, match="'payees' is not supported"):
        Client(api_key="an-api-key").api("payees")  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("read", "api_name", "endpoint", "expected_args", "expected_kwargs"),
    [
        pytest.param(
            lambda c: c.budgets(),
            "budget",
            "get_plans",
            (),
            {"include_accounts": False},
            id="budgets lists the plans without their accounts",
        ),
        pytest.param(
            lambda c: c.budgets(include_accounts=True),
            "budget",
            "get_plans",
            (),
            {"include_accounts": True},
            id="budgets can ask for the accounts too",
        ),
        pytest.param(
            lambda c: c.budget(BUDGET_ID),
            "budget",
            "get_plan_by_id",
            (),
            {"plan_id": BUDGET_ID},
            id="budget reads a single plan by id",
        ),
        pytest.param(
            lambda c: c.accounts(BUDGET_ID),
            "accounts",
            "get_accounts",
            (BUDGET_ID,),
            {},
            id="accounts reads the accounts of a budget",
        ),
    ],
)
def test_read_methods_call_their_endpoint_with_the_budget(
    client: Client,
    ynab_api: YnabClientStub,
    read,
    api_name: str,
    endpoint: str,
    expected_args: tuple,
    expected_kwargs: dict,
):
    read(client)

    api = ynab_api.api(api_name)  # type: ignore[arg-type]
    getattr(api, endpoint).assert_called_once_with(*expected_args, **expected_kwargs)


def test_transactions_of_an_account_trims_the_time_off_the_since_date(
    client: Client, ynab_api: YnabClientStub
):
    client.transactions(
        budget_id=BUDGET_ID,
        account_id=ACCOUNT_ID,
        since_date=dt.datetime(2025, 5, 15, 13, 45, 30, 123456),
    )

    ynab_api.api("transactions").get_transactions_by_account.assert_called_once_with(
        plan_id=BUDGET_ID,
        account_id=ACCOUNT_ID,
        since_date=dt.datetime(2025, 5, 15, 0, 0, 0, 0),
    )


@pytest.mark.parametrize(
    "since_date",
    [
        pytest.param(dt.date(2025, 5, 15), id="a plain date needs no normalisation"),
        pytest.param(None, id="no date asks YNAB for its own default window"),
    ],
)
def test_transactions_forwards_a_plain_date_untouched(
    client: Client, ynab_api: YnabClientStub, since_date: dt.date | None
):
    client.transactions(budget_id=BUDGET_ID, account_id=ACCOUNT_ID, since_date=since_date)

    call = ynab_api.api("transactions").get_transactions_by_account.call_args
    assert call.kwargs["since_date"] is since_date


@pytest.mark.parametrize(
    "account_id",
    [
        pytest.param(None, id="no account given"),
        pytest.param("", id="an empty account id"),
    ],
)
def test_transactions_without_an_account_reads_the_whole_budget(
    client: Client, ynab_api: YnabClientStub, account_id: str | None
):
    client.transactions(budget_id=BUDGET_ID, account_id=account_id)

    api = ynab_api.api("transactions")
    api.get_transactions.assert_called_once_with(plan_id=BUDGET_ID, since_date=None)
    api.get_transactions_by_account.assert_not_called()


def test_create_transactions_does_not_reach_ynab_with_nothing_to_create(
    client: Client, ynab_api: YnabClientStub
):
    assert (
        client.create_transactions(budget_id=BUDGET_ID, account_id=ACCOUNT_ID, transactions=[])
        == []
    )
    assert ynab_api.registry == {}


def created_by(ynab_api: YnabClientStub) -> list:
    return list(
        ynab_api.api("transactions").create_transaction.call_args.kwargs["data"].transactions
    )


@pytest.mark.parametrize(
    ("amount", "expected_milliunits"),
    [
        pytest.param(10.0, 10000, id="a whole inflow"),
        pytest.param(-25.5, -25500, id="an outflow with one decimal"),
        pytest.param(-0.15, -150, id="a small outflow of cents"),
        pytest.param(2.01, 2010, id="an amount a float cannot represent exactly"),
    ],
)
def test_create_transactions_converts_amounts_to_milliunits(
    client: Client, ynab_api: YnabClientStub, amount: float, expected_milliunits: int
):
    client.create_transactions(
        budget_id=BUDGET_ID,
        account_id=ACCOUNT_ID,
        transactions=[PendingImportFactory(amount=amount)],
    )

    assert created_by(ynab_api)[0].amount == expected_milliunits


def test_create_transactions_sends_the_import_id_the_account_and_the_bank_payee(
    client: Client, ynab_api: YnabClientStub
):
    pending = PendingImportFactory(payee="COMPRA EN MERCADONA 4412", amount=-12.34)

    client.create_transactions(budget_id=BUDGET_ID, account_id=ACCOUNT_ID, transactions=[pending])

    call = ynab_api.api("transactions").create_transaction.call_args
    assert call.args == (BUDGET_ID,)
    [created] = call.kwargs["data"].transactions
    assert created.account_id == UUID(ACCOUNT_ID)
    assert created.import_id == pending.import_id
    assert created.var_date == pending.transaction.date
    # The payee is left unresolved so YNAB can apply its own rename rules to the import
    assert created.payee_name == "COMPRA EN MERCADONA 4412"
    assert created.payee_id is None
    # YNAB keeps imported transactions in the "unapproved" inbox until the user reviews them
    assert created.approved is False


def test_create_transactions_cuts_a_payee_to_the_length_ynab_accepts(
    client: Client, ynab_api: YnabClientStub
):
    long_payee = "TRANSFERENCIA " + "X" * 300

    client.create_transactions(
        budget_id=BUDGET_ID,
        account_id=ACCOUNT_ID,
        transactions=[PendingImportFactory(payee=long_payee), PendingImportFactory(payee="BAR")],
    )

    assert [t.payee_name for t in created_by(ynab_api)] == [long_payee[:200], "BAR"]


@pytest.mark.parametrize(
    "cleared",
    [
        pytest.param(TransactionClearedStatus.CLEARED, id="an ordinary import"),
        pytest.param(TransactionClearedStatus.RECONCILED, id="a reconciling import"),
    ],
)
def test_create_transactions_applies_the_same_cleared_status_to_every_row(
    client: Client, ynab_api: YnabClientStub, cleared: TransactionClearedStatus
):
    client.create_transactions(
        budget_id=BUDGET_ID,
        account_id=ACCOUNT_ID,
        transactions=[PendingImportFactory(), PendingImportFactory(amount=-3.0)],
        cleared=cleared,
    )

    assert [t.cleared for t in created_by(ynab_api)] == [cleared, cleared]


@pytest.mark.parametrize(
    ("answer", "expected"),
    [
        pytest.param(["YNAB:-10000:2025-05-15:1"], ["YNAB:-10000:2025-05-15:1"], id="a rejection"),
        pytest.param(None, [], id="a response that omits the field"),
    ],
)
def test_create_transactions_returns_the_import_ids_ynab_rejected(
    client: Client, ynab_api: YnabClientStub, answer: list[str] | None, expected: list[str]
):
    api = ynab_api.api("transactions")
    api.create_transaction.return_value.data.duplicate_import_ids = answer

    duplicates = client.create_transactions(
        budget_id=BUDGET_ID, account_id=ACCOUNT_ID, transactions=[PendingImportFactory()]
    )

    assert duplicates == expected


def test_update_transactions_does_not_reach_ynab_with_nothing_to_update(
    client: Client, ynab_api: YnabClientStub
):
    client.update_transactions(
        budget_id=BUDGET_ID, transaction_ids=[], cleared=TransactionClearedStatus.RECONCILED
    )

    assert ynab_api.registry == {}


def test_update_transactions_patches_each_transaction_by_id(
    client: Client, ynab_api: YnabClientStub
):
    client.update_transactions(
        budget_id=BUDGET_ID,
        transaction_ids=["t-1", "t-2"],
        cleared=TransactionClearedStatus.RECONCILED,
    )

    call = ynab_api.api("transactions").update_transactions.call_args
    assert call.kwargs["plan_id"] == BUDGET_ID
    updated = call.kwargs["data"].transactions
    assert [(t.id, t.cleared) for t in updated] == [
        ("t-1", TransactionClearedStatus.RECONCILED),
        ("t-2", TransactionClearedStatus.RECONCILED),
    ]


def test_update_transactions_sends_no_account_so_a_moved_transaction_stays_where_it_is(
    client: Client, ynab_api: YnabClientStub
):
    client.update_transactions(
        budget_id=BUDGET_ID, transaction_ids=["t-1"], cleared=TransactionClearedStatus.RECONCILED
    )

    data = ynab_api.api("transactions").update_transactions.call_args.kwargs["data"]
    assert data.to_dict() == {"transactions": [{"id": "t-1", "cleared": "reconciled"}]}


def test_account_reads_one_account_by_its_uuid(client: Client, ynab_api: YnabClientStub):
    api = ynab_api.api("accounts")

    account = client.account(BUDGET_ID, ACCOUNT_ID)

    api.get_account_by_id.assert_called_once_with(plan_id=BUDGET_ID, account_id=UUID(ACCOUNT_ID))
    assert account is api.get_account_by_id.return_value.data.account


@pytest.mark.parametrize(
    ("answer", "exists"),
    [
        pytest.param(None, True, id="found"),
        pytest.param(ApiException(status=404, reason="Not Found"), False, id="404 means gone"),
    ],
)
def test_transaction_exists_reads_the_transaction_by_id(
    client: Client, ynab_api: YnabClientStub, answer: ApiException | None, exists: bool
):
    api = ynab_api.api("transactions")
    api.get_transaction_by_id.side_effect = answer

    assert client.transaction_exists(BUDGET_ID, "t-1") is exists
    api.get_transaction_by_id.assert_called_once_with(plan_id=BUDGET_ID, transaction_id="t-1")


def test_transaction_exists_lets_other_errors_through(client: Client, ynab_api: YnabClientStub):
    ynab_api.api("transactions").get_transaction_by_id.side_effect = ApiException(status=500)

    with pytest.raises(ApiException):
        client.transaction_exists(BUDGET_ID, "t-1")


@pytest.fixture
def silent_ynab() -> Iterator[str]:
    """A server that accepts the connection and never answers, like a stalled YNAB."""
    with socket.socket() as server:
        server.bind(("127.0.0.1", 0))
        server.listen(8)
        yield f"http://127.0.0.1:{server.getsockname()[1]}"


def test_a_request_that_gets_no_answer_gives_up_with_one_line(
    silent_ynab: str, monkeypatch: pytest.MonkeyPatch
):
    # urllib3 tries four times; the server never answers, so a short read wait is enough
    monkeypatch.setattr(client_module, "REQUEST_TIMEOUT", (0.2, 0.05))
    client = Client(api_key="an-api-key")
    client._Client__client.configuration.host = silent_ynab  # type: ignore[attr-defined]

    started = time.monotonic()
    with pytest.raises(YNAB_ERRORS) as raised:
        client.budgets()

    assert time.monotonic() - started < 10
    assert timed_out(raised.value)
    assert ynab_error_message(raised.value) == (
        "YNAB did not answer in time. Check your internet connection and try again."
    )
    assert web_error_message(raised.value) == YNAB_TIMED_OUT
