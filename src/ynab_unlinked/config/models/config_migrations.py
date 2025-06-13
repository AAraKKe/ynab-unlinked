from __future__ import annotations

import shutil

from ynab_unlinked.config.migrations.base import Delta
from ynab_unlinked.ynab_api import Client

from .v1 import ConfigV1
from .v2 import Budget, ConfigV2, CurrencyFormat


class DeltaConfigV1ToV2(Delta[ConfigV1, ConfigV2]):
    origin = ConfigV1.version()
    destination = ConfigV2.version()

    def on_migrate(self, origin: ConfigV1) -> ConfigV2:
        client = Client(origin.api_key)

        budget_details = client.budget(origin.budget_id)
        if budget_details is None:
            raise ValueError(f"Could not find budget with ID {origin.budget_id}")

        if budget_details.currency_format is None:
            raise ValueError(f"Budget {budget_details.name!r} has no currency format")

        if budget_details.date_format is None:
            raise ValueError(f"Budget {budget_details.name!r} has no date format")

        # Create CurrencyFormat from budget details
        currency_format = CurrencyFormat(
            iso_code=budget_details.currency_format.iso_code,
            decimal_digits=budget_details.currency_format.decimal_digits,
            decimal_separator=budget_details.currency_format.decimal_separator,
            symbol_first=budget_details.currency_format.symbol_first,
            group_separator=budget_details.currency_format.group_separator,
            currency_symbol=budget_details.currency_format.currency_symbol,
            display_symbol=budget_details.currency_format.display_symbol,
        )

        # Create Budget object
        budget = Budget(
            id=budget_details.id,
            name=budget_details.name,
            date_format=budget_details.date_format.format,
            currency_format=currency_format,
        )

        # Create and return ConfigV2 with all fields
        config_v2 = ConfigV2(
            api_key=origin.api_key,
            budget=budget,
            last_reconciliation_date=origin.last_reconciliation_date,
            entities=origin.entities,
            payee_rules=origin.payee_rules,
        )

        # Now we delete v1 and save v2
        # This is special because v1 is stored in a different path than any other versions
        shutil.rmtree(ConfigV1.path().parent)
        config_v2.save()

        return config_v2

    def on_rollback(self, destination: ConfigV2) -> ConfigV1:
        config_v1 = ConfigV1(
            api_key=destination.api_key,
            budget_id=destination.budget.id,
            last_reconciliation_date=destination.last_reconciliation_date,
            entities=destination.entities,
            payee_rules=destination.payee_rules,
        )

        # Ensure we store it on the expected place of v1
        ConfigV1.path().parent.mkdir(parents=True, exist_ok=True)
        config_v1.save()
        # And now delete the other config
        ConfigV2.path().unlink()

        return config_v1
