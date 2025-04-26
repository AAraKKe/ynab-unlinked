import datetime as dt
import ynab

from ynab_unlinked.config import Config
from ynab_unlinked.models import Transaction


class Client:
    def __init__(self, config: Config):
        self.config = config
        self.__client = ynab.ApiClient(ynab.Configuration(access_token=config.api_key))

    def budgets(self) -> list[ynab.BudgetSummary]:
        api = ynab.BudgetsApi(self.__client)
        response = api.get_budgets(include_accounts=True)
        return response.data.budgets

    def transactions(
        self, since_date: dt.date | None = None
    ) -> list[ynab.TransactionDetail]:
        api = ynab.TransactionsApi(self.__client)
        response = api.get_transactions_by_account(
            budget_id=self.config.budget_id,
            account_id=self.config.account_id,
            since_date=since_date,
        )

        return response.data.transactions

    def payees(self) -> list[ynab.Payee]:
        api = ynab.PayeesApi(self.__client)
        response = api.get_payees(self.config.budget_id)
        return response.data.payees

    def create_transactions(self, transactions: list[Transaction]):
        if not transactions:
            return

        api = ynab.TransactionsApi(self.__client)

        transactions_to_create = [
            ynab.NewTransaction(
                account_id=self.config.account_id,
                date=t.date,
                payee_id=t.payee_id,
                payee_name=t.ynab_payee,
                cleared=t.ynab_cleared_status,
                amount=int(t.amount * 1000),
                approved=True,
            )
            for t in transactions
        ]
        api.create_transaction(
            self.config.budget_id,
            data=ynab.PostTransactionsWrapper(transactions=transactions_to_create),
        )

    def update_transactions(self, transactions: list[Transaction]):
        if not transactions:
            return

        api = ynab.TransactionsApi(self.__client)

        transactions_to_update = [
            ynab.SaveTransactionWithIdOrImportId(
                id=t.ynab_id,
                cleared=t.ynab_cleared_status,
                approved=True,
            )
            for t in transactions
        ]
        api.update_transactions(
            self.config.budget_id,
            data=ynab.PatchTransactionsWrapper(transactions=transactions_to_update),
        )
