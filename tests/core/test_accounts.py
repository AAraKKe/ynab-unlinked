import uuid

import pytest

from tests.factories import AccountFactory, StoredAccountFactory
from ynab_unlinked.core.accounts import AccountState, account_state

SAVED = str(uuid.UUID(int=10))
OTHER = str(uuid.UUID(int=20))


@pytest.mark.parametrize(
    ("accounts", "expected"),
    [
        ([AccountFactory(id=OTHER), AccountFactory(id=SAVED)], AccountState.OPEN),
        ([AccountFactory(id=SAVED, closed=True)], AccountState.CLOSED),
        ([AccountFactory(id=SAVED, deleted=True)], AccountState.MISSING),
        ([AccountFactory(id=OTHER)], AccountState.MISSING),
        ([], AccountState.MISSING),
        ([StoredAccountFactory(id=OTHER), StoredAccountFactory(id=SAVED)], AccountState.OPEN),
        ([StoredAccountFactory(id=SAVED, closed=True)], AccountState.CLOSED),
        ([StoredAccountFactory(id=OTHER)], AccountState.MISSING),
    ],
    ids=[
        "open in ynab",
        "closed in ynab",
        "deleted in ynab",
        "not among ynab's accounts",
        "a budget without accounts",
        "open in the budget copy",
        "closed in the budget copy",
        "not in the budget copy",
    ],
)
def test_the_state_of_a_saved_account(accounts: list, expected: AccountState):
    assert account_state(SAVED, accounts) is expected
