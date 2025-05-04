import datetime as dt

import ynab

from ynab_unlinked.config import Config
from ynab_unlinked.models import TransactionWithYnabData


class Client:
    def __init__(self, config: Config):
        self.config = config
        self.__client = ynab.ApiClient(ynab.Configuration(access_token=config.api_key))

    def budgets(self, include_accounts: bool = False) -> list[ynab.BudgetSummary]:
        api = ynab.BudgetsApi(self.__client)
        response = api.get_budgets(include_accounts=include_accounts)
        return response.data.budgets

    def accounts(self) -> list[ynab.Account]:
        api = ynab.AccountsApi(self.__client)
        response = api.get_accounts(self.config.budget_id)
        return response.data.accounts

    def transactions(
        self, account_id: str, since_date: dt.date | None = None
    ) -> list[ynab.TransactionDetail]:
        api = ynab.TransactionsApi(self.__client)
        response = api.get_transactions_by_account(
            budget_id=self.config.budget_id,
            account_id=account_id,
            since_date=since_date,
        )

        return response.data.transactions

    def payees(self) -> list[ynab.Payee]:
        api = ynab.PayeesApi(self.__client)
        response = api.get_payees(self.config.budget_id)
        return response.data.payees

    def create_transactions(
        self, account_id: str, transactions: list[TransactionWithYnabData]
    ):
        if not transactions:
            return

        api = ynab.TransactionsApi(self.__client)

        transactions_to_create = [
            ynab.NewTransaction(
                account_id=account_id,
                date=t.date,
                payee_id=t.ynab_payee_id,
                payee_name=t.ynab_payee,
                cleared=t.cleared,
                amount=int(t.amount * 1000),
                approved=True,
                import_id=t.id,
            )
            for t in transactions
        ]

        api.create_transaction(
            self.config.budget_id,
            data=ynab.PostTransactionsWrapper(transactions=transactions_to_create),
        )

    def update_transactions(self, transactions: list[TransactionWithYnabData]):
        if not transactions:
            return

        api = ynab.TransactionsApi(self.__client)

        transactions_to_update = [
            ynab.SaveTransactionWithIdOrImportId(
                id=t.ynab_id,
                cleared=t.cleared,
                approved=True,
            )
            for t in transactions
        ]
        api.update_transactions(
            self.config.budget_id,
            data=ynab.PatchTransactionsWrapper(transactions=transactions_to_update),
        )
