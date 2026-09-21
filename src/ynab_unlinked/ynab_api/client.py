import datetime as dt
from typing import Literal, TypedDict, overload
from uuid import UUID

from ynab import (
    Account,
    AccountsApi,
    ApiClient,
    Configuration,
    NewTransaction,
    PatchTransactionsWrapper,
    Payee,
    PayeesApi,
    PlanDetail,
    PlansApi,
    PlanSummary,
    PostTransactionsWrapper,
    SaveTransactionWithIdOrImportId,
    TransactionDetail,
    TransactionsApi,
)

from ynab_unlinked.models import TransactionWithYnabData


class ApisType(TypedDict):
    budget: type[PlansApi]
    accounts: type[AccountsApi]
    transactions: type[TransactionsApi]
    payees: type[PayeesApi]


SupportedApisType = PlansApi | AccountsApi | TransactionsApi | PayeesApi
SupportedApisNames = Literal["budget", "accounts", "transactions", "payees"]


class Client:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.__client = ApiClient(Configuration(access_token=api_key))
        self._apis: ApisType = {
            "budget": PlansApi,
            "accounts": AccountsApi,
            "transactions": TransactionsApi,
            "payees": PayeesApi,
        }

    @overload
    def api(self, api_name: Literal["budget"]) -> PlansApi: ...

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

    def budgets(self, include_accounts: bool = False) -> list[PlanSummary]:
        api = self.api("budget")
        response = api.get_plans(include_accounts=include_accounts)
        return response.data.plans

    def budget(self, budget_id: str) -> PlanDetail:
        api = self.api("budget")
        response = api.get_plan_by_id(plan_id=budget_id)
        return response.data.plan

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
                plan_id=budget_id,
                account_id=account_id,
                since_date=since_date,
            )
        else:
            response = api.get_transactions(
                plan_id=budget_id,
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

        account_uuid = UUID(account_id)
        transactions_to_create = [
            NewTransaction(
                account_id=account_uuid,
                date=t.date,
                payee_id=UUID(t.ynab_payee_id) if t.ynab_payee_id else None,
                payee_name=t.ynab_payee,
                cleared=t.cleared,
                amount=round(t.amount * 1000),
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
        if not transactions:
            return

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
            plan_id=budget_id,
            data=PatchTransactionsWrapper(transactions=to_update),
        )
