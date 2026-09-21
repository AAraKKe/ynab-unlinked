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
    PlanDetail,
    PlansApi,
    PlanSummary,
    PostTransactionsWrapper,
    SaveTransactionWithIdOrImportId,
    TransactionClearedStatus,
    TransactionDetail,
    TransactionsApi,
)

from ynab_unlinked.models import PendingImport, milliunits


class ApisType(TypedDict):
    budget: type[PlansApi]
    accounts: type[AccountsApi]
    transactions: type[TransactionsApi]


SupportedApisType = PlansApi | AccountsApi | TransactionsApi
SupportedApisNames = Literal["budget", "accounts", "transactions"]


class Client:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.__client = ApiClient(Configuration(access_token=api_key))
        self._apis: ApisType = {
            "budget": PlansApi,
            "accounts": AccountsApi,
            "transactions": TransactionsApi,
        }

    @overload
    def api(self, api_name: Literal["budget"]) -> PlansApi: ...

    @overload
    def api(self, api_name: Literal["accounts"]) -> AccountsApi: ...

    @overload
    def api(self, api_name: Literal["transactions"]) -> TransactionsApi: ...

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

    def create_transactions(
        self,
        budget_id: str,
        account_id: str,
        transactions: list[PendingImport],
        cleared: TransactionClearedStatus = TransactionClearedStatus.CLEARED,
    ) -> list[str]:
        """Import the transactions and return the import ids YNAB rejected as duplicates."""
        if not transactions:
            return []

        api = self.api("transactions")

        account_uuid = UUID(account_id)
        transactions_to_create = [
            NewTransaction(
                account_id=account_uuid,
                date=pending.transaction.date,
                payee_name=pending.transaction.payee,
                cleared=cleared,
                amount=milliunits(pending.transaction.amount),
                approved=False,
                import_id=pending.import_id,
            )
            for pending in transactions
        ]

        response = api.create_transaction(
            budget_id,
            data=PostTransactionsWrapper(transactions=transactions_to_create),
        )

        return response.data.duplicate_import_ids or []

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
