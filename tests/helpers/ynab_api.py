import datetime as dt
from unittest.mock import MagicMock

from ynab import (
    CategoriesResponse,
    CategoriesResponseData,
    Category,
    MonthDetail,
    MonthDetailResponse,
    MonthDetailResponseData,
    MonthSummariesResponse,
    MonthSummariesResponseData,
)

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

    def accounts(self) -> MagicMock:
        return self.registry.get("accounts")

    def transactions(self) -> MagicMock:
        return self.registry.get("transactions")
