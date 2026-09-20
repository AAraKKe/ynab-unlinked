from pathlib import Path

import pytest
from ynab import TransactionDetail

from tests.helpers.config import ConfigFiles
from tests.helpers.ynab_api import YnabClientStub
from tests.process.builders import write_config


@pytest.fixture
def config_file(config: str, config_files: ConfigFiles) -> Path:
    """The checked in asset registers the test entity under a non UUID account id, which
    the YNAB client rejects on upload, so these tests start from their own config."""
    write_config(config_files.v2)
    return config_files.v2


@pytest.fixture
def ynab(ynab_api: YnabClientStub) -> YnabClientStub:
    """The YNAB stub answering with an empty budget."""
    ynab_api.api("transactions").get_transactions_by_account.return_value.data.transactions = []
    ynab_api.api("payees").get_payees.return_value.data.payees = []
    return ynab_api


@pytest.fixture
def existing_in_ynab(ynab: YnabClientStub):
    def setup(transactions: list[TransactionDetail]) -> None:
        api = ynab.api("transactions")
        api.get_transactions_by_account.return_value.data.transactions = transactions

    return setup


@pytest.fixture
def created_transactions(ynab: YnabClientStub):
    def read() -> list:
        call = ynab.api("transactions").create_transaction.call_args
        assert call is not None, "No transaction was created in YNAB"
        return list(call.kwargs["data"].transactions)

    return read
