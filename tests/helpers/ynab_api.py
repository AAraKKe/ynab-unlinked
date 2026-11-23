import datetime as dt
from unittest.mock import MagicMock

from ynab import (
    Account,
    CategoriesResponse,
    CategoriesResponseData,
    Category,
    MonthDetail,
    MonthDetailResponse,
    MonthDetailResponseData,
    MonthSummariesResponse,
    MonthSummariesResponseData,
    PostTransactionsWrapper,
    SaveTransactionsResponse,
    SaveTransactionsResponseData,
    TransactionDetail,
)

from tests.factories import TransactionDetailFactory
from ynab_unlinked.ynab_api.client import Client, SupportedApisNames


def month_response(month: dt.date, categories: list[Category] | None = None) -> MonthDetailResponse:
    """What YNAB answers for one month: its categories as they stood in it."""
    detail = MonthDetail(
        month=month,
        income=0,
        budgeted=0,
        activity=0,
        to_be_budgeted=0,
        deleted=False,
        categories=categories or [],
    )
    return MonthDetailResponse(data=MonthDetailResponseData(month=detail))


class YnabClientStub(Client):
    def __init__(self, *args, **kwargs):
        self.registry: dict[SupportedApisNames, MagicMock] = {}
        super().__init__(*args, **kwargs)

    def api(self, api_name: SupportedApisNames) -> MagicMock:
        registered_mock = self.registry.get(api_name)

        if registered_mock is None:
            registered_mock = MagicMock(spec=self._apis.get(api_name))
            if api_name == "categories":
                # Every sync reads the categories: a budget without any unless a test says so
                registered_mock.get_categories.return_value = CategoriesResponse(
                    data=CategoriesResponseData(category_groups=[], server_knowledge=0)
                )
            if api_name == "months":
                registered_mock.get_plan_months.return_value = MonthSummariesResponse(
                    data=MonthSummariesResponseData(months=[], server_knowledge=0)
                )
                # A sync asks for each past month it lists: without categories unless a test
                # says so
                registered_mock.get_plan_month.side_effect = lambda _, month: month_response(month)
            self.registry[api_name] = registered_mock

        return registered_mock

    def budget(self) -> MagicMock:
        return self.registry.get("budget")

    def answer_accounts(self, *accounts: Account) -> None:
        """The accounts of the budget YNAB lists. `yul load` checks the saved one is open."""
        self.api("accounts").get_accounts.return_value.data.accounts = list(accounts)

    def refuse_import_ids(self, *import_ids: str) -> None:
        """Answer creating transactions as YNAB does, which never takes an import id twice.

        A sent row is not created, and comes back in `duplicate_import_ids`, when YNAB had
        its import id before:

        - one of `import_ids`, in any account: a transaction imported once and deleted in
          YNAB since, whose id YNAB keeps for good;
        - an id an earlier request of the test created in the same account: YNAB holds that
          transaction, as when two files of one import share a row.

        The other rows are created, and remembered. Only ids that were sent come back.
        """
        refused = frozenset(import_ids)
        held: dict[str, set[str | None]] = {}

        def create(budget_id: str, data: PostTransactionsWrapper) -> SaveTransactionsResponse:
            created: list[TransactionDetail] = []
            duplicates: list[str] = []
            for t in data.transactions or []:
                in_account = held.setdefault(str(t.account_id), set())
                if t.import_id in refused or t.import_id in in_account:
                    duplicates.append(t.import_id)
                    continue
                if t.import_id is not None:
                    in_account.add(t.import_id)
                created.append(
                    TransactionDetailFactory(
                        id=f"created-{t.import_id}",
                        import_id=t.import_id,
                        account_id=t.account_id,
                        var_date=t.var_date,
                        amount=t.amount,
                        payee_name=t.payee_name,
                        cleared=t.cleared,
                        approved=t.approved,
                    )
                )
            return SaveTransactionsResponse(
                data=SaveTransactionsResponseData(
                    transaction_ids=[t.id for t in created],
                    transactions=created,
                    duplicate_import_ids=duplicates,
                    server_knowledge=0,
                )
            )

        self.api("transactions").create_transaction.side_effect = create

    def accounts(self) -> MagicMock:
        return self.registry.get("accounts")

    def transactions(self) -> MagicMock:
        return self.registry.get("transactions")
