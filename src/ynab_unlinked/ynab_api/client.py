import datetime as dt
from typing import Literal, TypedDict, overload

from ynab.api.accounts_api import AccountsApi
from ynab.api.budgets_api import BudgetsApi
from ynab.api.payees_api import PayeesApi
from ynab.api.transactions_api import TransactionsApi
from ynab.api_client import ApiClient
from ynab.configuration import Configuration
from ynab.models.account import Account
from ynab.models.budget_detail import BudgetDetail
from ynab.models.budget_summary import BudgetSummary
from ynab.models.new_transaction import NewTransaction
from ynab.models.patch_transactions_wrapper import PatchTransactionsWrapper
from ynab.models.payee import Payee
from ynab.models.post_transactions_wrapper import PostTransactionsWrapper
from ynab.models.save_transaction_with_id_or_import_id import SaveTransactionWithIdOrImportId
from ynab.models.transaction_detail import TransactionDetail

from ynab_unlinked.models import TransactionWithYnabData


class ApisType(TypedDict):
    budget: type[BudgetsApi]
    accounts: type[AccountsApi]
    transactions: type[TransactionsApi]
    payees: type[PayeesApi]


SupportedApisType = BudgetsApi | AccountsApi | TransactionsApi | PayeesApi
SupportedApisNames = Literal["budget", "accounts", "transactions", "payees"]


class Client:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.__client = ApiClient(Configuration(access_token=api_key))
        self._apis: ApisType = {
            "budget": BudgetsApi,
            "accounts": AccountsApi,
            "transactions": TransactionsApi,
            "payees": PayeesApi,
        }

    @overload
    def api(self, api_name: Literal["budget"]) -> BudgetsApi: ...

    @overload
    def api(self, api_name: Literal["accounts"]) -> AccountsApi: ...

    @overload
    def api(self, api_name: Literal["transactions"]) -> TransactionsApi: ...

    @overload
    def api(self, api_name: Literal["payees"]) -> PayeesApi: ...

    def api(self, api_name: SupportedApisNames) -> SupportedApisType:
        if (api := self._apis.get(api_name)) is None:
            raise ValueError(f"The api {api_name!r} is not supported")

        return api(self.__client)

    def budgets(self, include_accounts: bool = False) -> list[BudgetSummary]:
        api = self.api("budget")
        response = api.get_budgets(include_accounts=include_accounts)
        return response.data.budgets

    def budget(self, budget_id: str) -> BudgetDetail:
        api = self.api("budget")
        response = api.get_budget_by_id(budget_id=budget_id)
        return response.data.budget

    def accounts(self, budget_id: str) -> list[Account]:
        api = self.api("accounts")
        response = api.get_accounts(budget_id)
        return response.data.accounts

    def transactions(
        self,
        budget_id: str,
        account_id: str | None = None,
        since_date: dt.datetime | dt.date | None = None,
    ) -> list[TransactionDetail]:
        api = self.api("transactions")

        if since_date is not None and isinstance(since_date, dt.datetime):
            since_date = since_date.replace(hour=0, minute=0, second=0, microsecond=0)

        if account_id:
            response = api.get_transactions_by_account(
                budget_id=budget_id,
                account_id=account_id,
                since_date=since_date,
            )
        else:
            response = api.get_transactions(
                budget_id=budget_id,
                since_date=since_date,
            )

        return response.data.transactions

    def payees(self, budget_id: str) -> list[Payee]:
        api = self.api("payees")
        response = api.get_payees(budget_id)
        return response.data.payees

    def create_transactions(
        self,
        budget_id: str,
        account_id: str,
        transactions: list[TransactionWithYnabData],
    ):
        if not transactions:
            return

        api = self.api("transactions")

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
            budget_id,
            data=PostTransactionsWrapper(transactions=transactions_to_create),
        )

    def update_transactions(self, budget_id: str, transactions: list[TransactionDetail]):
        api = self.api("transactions")

        to_update = [
            SaveTransactionWithIdOrImportId(
                id=t.id,
                account_id=t.account_id,
                cleared=t.cleared,
            )
            for t in transactions
        ]
        api.update_transactions(
            budget_id=budget_id,
            data=PatchTransactionsWrapper(transactions=to_update),
        )
