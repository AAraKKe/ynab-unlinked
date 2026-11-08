import pytest

from tests.helpers.ynab_api import YnabClientStub
from ynab_unlinked.ynab_api import Client

BUDGET_ID = "00000000-0000-0000-0000-000000000001"


@pytest.fixture
def client(ynab_api: YnabClientStub) -> Client:
    """A real client whose SDK calls land on the `ynab_api` stub."""
    return Client("api-key")
