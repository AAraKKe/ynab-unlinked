from unittest.mock import MagicMock

from ynab_unlinked.ynab_api.client import Client, SupportedApisNames


class YnabClientStub(Client):
    def __init__(self, *args, **kwargs):
        self.registry: dict[SupportedApisNames, MagicMock] = {}
        super().__init__(*args, **kwargs)

    def api(self, api_name: SupportedApisNames) -> MagicMock:
        registered_mock = self.registry.get(api_name)

        if registered_mock is None:
            registered_mock = MagicMock(spec=self._apis.get(api_name))
            self.registry[api_name] = registered_mock

        return registered_mock

    def budget(self) -> MagicMock:
        return self.registry.get("budget")

    def accounts(self) -> MagicMock:
        return self.registry.get("accounts")

    def transactions(self) -> MagicMock:
        return self.registry.get("transactions")

    def payees(self) -> MagicMock:
        return self.registry.get("payees")
