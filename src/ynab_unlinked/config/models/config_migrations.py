from __future__ import annotations

import shutil
from contextlib import suppress

from ynab_unlinked.config.migrations.base import Delta
from ynab_unlinked.ynab_api import Client

from .shared import EntityConfig, EntityConfigV3
from .v1 import ConfigV1
from .v2 import Budget, ConfigV2, CurrencyFormat
from .v3 import ConfigV3
from .v4 import ConfigV4, LoaderConfig


class DeltaConfigV1ToV2(Delta[ConfigV1, ConfigV2]):
    origin = ConfigV1.version()
    destination = ConfigV2.version()

    def on_migrate(self, origin: ConfigV1) -> ConfigV2:
        client = Client(origin.api_key)

        budget_details = client.budget(origin.budget_id)

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
            id=str(budget_details.id),
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

        # Save v2 before deleting v1, so a failed save leaves the old config in place.
        # This is special because v1 is stored in a different path than any other versions
        config_v2.save()
        # Gone already when another run removed it first
        with suppress(FileNotFoundError):
            shutil.rmtree(ConfigV1.path().parent)

        return config_v2

    def on_rollback(self, destination: ConfigV2) -> ConfigV1:
        config_v1 = ConfigV1(
            api_key=destination.api_key,
            budget_id=destination.budget.id,
            last_reconciliation_date=destination.last_reconciliation_date,
            entities=destination.entities,
            payee_rules=destination.payee_rules,
        )

        # save() creates the V1 folder, which lives apart from the others
        config_v1.save()
        # And now delete the other config
        ConfigV2.path().unlink()

        return config_v1


class DeltaConfigV2ToV3(Delta[ConfigV2, ConfigV3]):
    origin = ConfigV2.version()
    destination = ConfigV3.version()

    def on_migrate(self, origin: ConfigV2) -> ConfigV3:
        # Payee rules and checkpoints are gone in V3: YNAB renames payees itself and the
        # import id identifies a transaction, so neither is read any more.
        config_v3 = ConfigV3(
            api_key=origin.api_key,
            budget=origin.budget,
            last_reconciliation_date=origin.last_reconciliation_date,
            entities={
                name: EntityConfigV3(account_id=entity.account_id)
                for name, entity in origin.entities.items()
            },
        )

        # V2 and V3 live in the same file, so saving replaces the migrated away config
        config_v3.save()

        return config_v3

    def on_rollback(self, destination: ConfigV3) -> ConfigV2:
        config_v2 = ConfigV2(
            api_key=destination.api_key,
            budget=destination.budget,
            last_reconciliation_date=destination.last_reconciliation_date,
            entities={
                name: EntityConfig(account_id=entity.account_id)
                for name, entity in destination.entities.items()
            },
        )

        config_v2.save()

        return config_v2


class DeltaConfigV3ToV4(Delta[ConfigV3, ConfigV4]):
    origin = ConfigV3.version()
    destination = ConfigV4.version()

    def on_migrate(self, origin: ConfigV3) -> ConfigV4:
        # Account settings, adjustments and debt mappings are new in V4. They start empty: every
        # open account counts in net worth with its defaults until the settings change it.
        config_v4 = ConfigV4(
            api_key=origin.api_key,
            budget=origin.budget,
            last_reconciliation_date=origin.last_reconciliation_date,
            loaders={
                name: LoaderConfig(account_id=entity.account_id)
                for name, entity in origin.entities.items()
            },
        )

        # V3 and V4 live in the same file, so saving replaces the migrated away config
        config_v4.save()

        return config_v4

    def on_rollback(self, destination: ConfigV4) -> ConfigV3:
        config_v3 = ConfigV3(
            api_key=destination.api_key,
            budget=destination.budget,
            last_reconciliation_date=destination.last_reconciliation_date,
            entities={
                name: EntityConfigV3(account_id=loader.account_id)
                for name, loader in destination.loaders.items()
            },
        )

        config_v3.save()

        return config_v3
