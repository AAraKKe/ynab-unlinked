import datetime as dt
import json
from pathlib import Path

from tests.factories import DEFAULT_DATE
from ynab_unlinked.config.models.v2 import ConfigV2

BUDGET_ID = "00000000-0000-0000-0000-000000000001"
ACCOUNT_ID = "00000000-0000-0000-0000-00000000000a"
OTHER_ACCOUNT_ID = "00000000-0000-0000-0000-00000000000b"
CLOSED_ACCOUNT_ID = "00000000-0000-0000-0000-00000000000c"
REGISTERED_ENTITY = {"test": {"account_id": ACCOUNT_ID, "checkpoint": None}}

# The export under test covers the days leading to the frozen `today`
THREE_DAYS_AGO = DEFAULT_DATE - dt.timedelta(days=3)
YESTERDAY = DEFAULT_DATE - dt.timedelta(days=1)
FIVE_DAYS_AGO = DEFAULT_DATE - dt.timedelta(days=5)
TODAY = dt.datetime.combine(DEFAULT_DATE, dt.time())


def write_config(
    path: Path,
    entities: dict[str, dict] | None = None,
    payee_rules: dict[str, list[str]] | None = None,
) -> None:
    path.write_text(
        json.dumps(
            {
                "api_key": "my-api-key",
                "budget": {
                    "id": BUDGET_ID,
                    "name": "My Budget",
                    "date_format": "DD/MM/YYYY",
                    "currency_format": {
                        "iso_code": "EUR",
                        "decimal_digits": 2,
                        "decimal_separator": ".",
                        "symbol_first": False,
                        "group_separator": ",",
                        "currency_symbol": "€",
                        "display_symbol": True,
                    },
                },
                "last_reconciliation_date": None,
                "entities": REGISTERED_ENTITY if entities is None else entities,
                "payee_rules": payee_rules or {},
                "version": "V2",
            }
        )
    )


def saved_config(config_file: Path) -> ConfigV2:
    return ConfigV2.model_validate_json(config_file.read_text())
