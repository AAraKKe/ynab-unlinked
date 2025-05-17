import datetime as dt

from ynab.api.accounts_api import AccountsApi
from ynab.api.budgets_api import BudgetsApi
from ynab.api.payees_api import PayeesApi
from ynab.api.transactions_api import TransactionsApi
from ynab.api_client import ApiClient
from ynab.configuration import Configuration
from ynab.models.account import Account
from ynab.models.budget_summary import BudgetSummary
from ynab.models.new_transaction import NewTransaction
from ynab.models.patch_transactions_wrapper import PatchTransactionsWrapper
from ynab.models.payee import Payee
from ynab.models.post_transactions_wrapper import PostTransactionsWrapper
from ynab.models.save_transaction_with_id_or_import_id import (
    SaveTransactionWithIdOrImportId,
)
from ynab.models.transaction_detail import TransactionDetail

from ynab_unlinked.config import Config
from ynab_unlinked.models import TransactionWithYnabData


class Client:
    def __init__(self, config: Config):
        self.config = config
        self.__client = ApiClient(Configuration(access_token=config.api_key))

    def budgets(self, include_accounts: bool = False) -> list[BudgetSummary]:
        api = BudgetsApi(self.__client)
        response = api.get_budgets(include_accounts=include_accounts)
        return response.data.budgets

    def accounts(self) -> list[Account]:
        api = AccountsApi(self.__client)
        response = api.get_accounts(self.config.budget_id)
        return response.data.accounts

    def transactions(
        self, account_id: str | None = None, since_date: dt.date | None = None
    ) -> list[TransactionDetail]:
        api = TransactionsApi(self.__client)

        if account_id:
            response = api.get_transactions_by_account(
                budget_id=self.config.budget_id,
                account_id=account_id,
                since_date=since_date,
            )
        else:
            response = api.get_transactions(
                budget_id=self.config.budget_id,
                since_date=since_date,
            )

        return response.data.transactions

    def payees(self) -> list[Payee]:
        api = PayeesApi(self.__client)
        response = api.get_payees(self.config.budget_id)
        return response.data.payees

    def create_transactions(
        self, account_id: str, transactions: list[TransactionWithYnabData]
    ):
        if not transactions:
            return

        api = TransactionsApi(self.__client)

        transactions_to_create = [
            NewTransaction(
                account_id=account_id,
                date=t.date,
                payee_name=t.payee,
                cleared=t.cleared,
                amount=int(t.amount * 1000),
                approved=False,
                import_id=t.id,
            )
            for t in transactions
        ]

        api.create_transaction(
            self.config.budget_id,
            data=PostTransactionsWrapper(transactions=transactions_to_create),
        )

    def update_transactions(self, transactions: list[TransactionDetail]):
        api = TransactionsApi(self.__client)

        to_update = [
            SaveTransactionWithIdOrImportId(
                id=t.id, account_id=t.account_id, cleared=t.cleared
            )
            for t in transactions
        ]
        api.update_transactions(
            budget_id=self.config.budget_id,
            data=PatchTransactionsWrapper(transactions=to_update),
        )
