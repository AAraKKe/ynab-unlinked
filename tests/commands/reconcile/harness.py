"""YNAB stubs and fixtures shared by the reconcile command tests."""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock

import pytest
from pytest_mock import MockerFixture
from ynab import Account, SaveTransactionWithIdOrImportId, TransactionDetail

from tests.commands.apps.reconcile.harness import (
    CHECKING_ID,
    CLEARED,
    RECONCILED,
    SAVINGS_ID,
    UNCLEARED,
)
from tests.helpers.ynab_api import YnabClientStub
from ynab_unlinked.choices import Choice
from ynab_unlinked.config import ConfigV2

__all__ = ["CHECKING_ID", "CLEARED", "RECONCILED", "SAVINGS_ID", "UNCLEARED"]

# Never returned by the accounts endpoint in these tests
CREDIT_ID = uuid.UUID("00000000-0000-0000-0000-00000000000c")


class TuiStub:
    """Stands in for the Textual app.

    It records what the command handed over, applies the selection a user would have made
    and returns the exit code the app would have produced.
    """

    def __init__(self, app_class: MagicMock):
        self.app_class = app_class
        self.exit_code: int = 0
        self.selected_ids: set[str] | None = None
        app_class.return_value.run.side_effect = self._run

    def _run(self) -> int:
        for account_choice in self.choices:
            if self.selected_ids is None:
                account_choice.select()
                continue
            for child in account_choice.choices:
                if child.id in self.selected_ids:
                    # The app lets uncleared transactions be picked through 'Include Uncleared'
                    child.disable_forced_selected()
                    child.select()
        return self.exit_code

    @property
    def choices(self) -> list[Choice]:
        return self.app_class.call_args.args[1]

    @property
    def formatter(self):
        return self.app_class.call_args.kwargs["formatter"]

    @property
    def config(self) -> ConfigV2:
        return self.app_class.call_args.args[0]


@pytest.fixture
def stored_config(config: str) -> ConfigV2:
    """The config the command will load. Changes made here must be saved to reach it."""
    return ConfigV2.load()


@pytest.fixture
def tui(mocker: MockerFixture) -> TuiStub:
    return TuiStub(mocker.patch("ynab_unlinked.commands.reconcile.Reconcile", autospec=True))


@pytest.fixture
def ynab(ynab_api: YnabClientStub) -> YnabClientStub:
    ynab_api.api("transactions")
    ynab_api.api("accounts")
    return ynab_api


def given_ynab_data(
    ynab: YnabClientStub, transactions: list[TransactionDetail], accounts: list[Account]
):
    ynab.transactions().get_transactions.return_value.data.transactions = transactions
    ynab.accounts().get_accounts.return_value.data.accounts = accounts


def updates_sent(ynab: YnabClientStub) -> list[SaveTransactionWithIdOrImportId]:
    api = ynab.transactions()
    api.update_transactions.assert_called_once()
    return api.update_transactions.call_args.kwargs["data"].transactions
