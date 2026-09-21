"""Every test here asserts on the call the wrapper makes to the generated YNAB API."""

import datetime as dt
from uuid import UUID

import pytest
from ynab import TransactionClearedStatus

from tests.factories import TransactionDetailFactory, TransactionWithYnabDataFactory
from tests.helpers.ynab_api import YnabClientStub
from ynab_unlinked.ynab_api.client import Client

BUDGET_ID = "00000000-0000-0000-0000-000000000001"
ACCOUNT_ID = "00000000-0000-0000-0000-00000000000a"
PAYEE_ID = "00000000-0000-0000-0000-0000000000b0"


@pytest.fixture
def client(ynab_api: YnabClientStub) -> Client:
    """A real client whose `api` is served by the shared stub registry."""
    return Client(api_key="an-api-key")


def test_api_rejects_an_unknown_name():
    with pytest.raises(ValueError, match="'budgets' is not supported"):
        Client(api_key="an-api-key").api("budgets")  # type: ignore[arg-type]


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
        pytest.param(
            lambda c: c.payees(BUDGET_ID),
            "payees",
            "get_payees",
            (BUDGET_ID,),
            {},
            id="payees reads the payees of a budget",
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
    client.create_transactions(budget_id=BUDGET_ID, account_id=ACCOUNT_ID, transactions=[])

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
        pytest.param(0.15, 150, id="a small inflow of cents"),
        pytest.param(-0.15, -150, id="a small outflow of cents"),
    ],
)
def test_create_transactions_converts_amounts_to_milliunits(
    client: Client, ynab_api: YnabClientStub, amount: float, expected_milliunits: int
):
    client.create_transactions(
        budget_id=BUDGET_ID,
        account_id=ACCOUNT_ID,
        transactions=[TransactionWithYnabDataFactory(amount=amount)],
    )

    assert created_by(ynab_api)[0].amount == expected_milliunits


def test_create_transactions_rounds_amounts_that_float_cannot_represent(
    client: Client, ynab_api: YnabClientStub
):
    client.create_transactions(
        budget_id=BUDGET_ID,
        account_id=ACCOUNT_ID,
        transactions=[TransactionWithYnabDataFactory(amount=2.01)],
    )

    assert created_by(ynab_api)[0].amount == 2010


def test_create_transactions_sends_the_import_id_and_the_target_account(
    client: Client, ynab_api: YnabClientStub
):
    transaction = TransactionWithYnabDataFactory(amount=-12.34)

    client.create_transactions(
        budget_id=BUDGET_ID, account_id=ACCOUNT_ID, transactions=[transaction]
    )

    call = ynab_api.api("transactions").create_transaction.call_args
    assert call.args == (BUDGET_ID,)
    [created] = call.kwargs["data"].transactions
    assert created.account_id == UUID(ACCOUNT_ID)
    assert created.import_id == transaction.id
    assert created.var_date == transaction.date
    assert created.cleared is TransactionClearedStatus.CLEARED
    # YNAB keeps imported transactions in the "unapproved" inbox until the user reviews them
    assert created.approved is False


@pytest.mark.parametrize(
    ("ynab_payee_id", "expected_payee_id"),
    [
        pytest.param(PAYEE_ID, UUID(PAYEE_ID), id="a resolved payee is linked by its id"),
        pytest.param(None, None, id="an unknown payee is created from its name alone"),
    ],
)
def test_create_transactions_sends_the_payee_resolved_against_ynab(
    client: Client,
    ynab_api: YnabClientStub,
    ynab_payee_id: str | None,
    expected_payee_id: UUID | None,
):
    transaction = TransactionWithYnabDataFactory(payee="COMPRA EN MERCADONA 4412")
    transaction.ynab_payee = "Mercadona"
    transaction.ynab_payee_id = ynab_payee_id

    client.create_transactions(
        budget_id=BUDGET_ID, account_id=ACCOUNT_ID, transactions=[transaction]
    )

    [created] = created_by(ynab_api)
    assert created.payee_name == "Mercadona"
    assert created.payee_id == expected_payee_id


def test_create_transactions_keeps_the_import_id_of_each_duplicate(
    client: Client, ynab_api: YnabClientStub
):
    first = TransactionWithYnabDataFactory(amount=-12.34)
    duplicate = TransactionWithYnabDataFactory(amount=-12.34)
    duplicate.counter = 1

    client.create_transactions(
        budget_id=BUDGET_ID, account_id=ACCOUNT_ID, transactions=[first, duplicate]
    )

    assert [t.import_id for t in created_by(ynab_api)] == [first.id, duplicate.id]
    assert first.id != duplicate.id


def test_update_transactions_does_not_reach_ynab_with_nothing_to_update(
    client: Client, ynab_api: YnabClientStub
):
    client.update_transactions(budget_id=BUDGET_ID, transactions=[])

    assert ynab_api.registry == {}


def test_update_transactions_patches_each_transaction_by_id(
    client: Client, ynab_api: YnabClientStub
):
    transactions = [
        TransactionDetailFactory(
            id="t-1", account_id=UUID(ACCOUNT_ID), cleared=TransactionClearedStatus.RECONCILED
        ),
        TransactionDetailFactory(
            id="t-2", account_id=UUID(ACCOUNT_ID), cleared=TransactionClearedStatus.CLEARED
        ),
    ]

    client.update_transactions(budget_id=BUDGET_ID, transactions=transactions)

    call = ynab_api.api("transactions").update_transactions.call_args
    assert call.kwargs["plan_id"] == BUDGET_ID
    updated = call.kwargs["data"].transactions
    assert [(t.id, t.cleared) for t in updated] == [
        ("t-1", TransactionClearedStatus.RECONCILED),
        ("t-2", TransactionClearedStatus.CLEARED),
    ]
    assert all(t.account_id == UUID(ACCOUNT_ID) for t in updated)
