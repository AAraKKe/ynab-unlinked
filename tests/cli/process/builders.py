import datetime as dt
import json
from pathlib import Path

from tests.factories import DEFAULT_DATE
from ynab_unlinked.config import LatestConfig

BUDGET_ID = "00000000-0000-0000-0000-000000000001"
ACCOUNT_ID = "00000000-0000-0000-0000-00000000000a"
OTHER_ACCOUNT_ID = "00000000-0000-0000-0000-00000000000b"
CLOSED_ACCOUNT_ID = "00000000-0000-0000-0000-00000000000c"
REGISTERED_LOADER = {"test": {"account_id": ACCOUNT_ID}}

# The export under test covers the days leading to the frozen `today`
THREE_DAYS_AGO = DEFAULT_DATE - dt.timedelta(days=3)
YESTERDAY = DEFAULT_DATE - dt.timedelta(days=1)
FIVE_DAYS_AGO = DEFAULT_DATE - dt.timedelta(days=5)
TODAY = dt.datetime.combine(DEFAULT_DATE, dt.time())


def write_config(path: Path, loaders: dict[str, dict] | None = None) -> None:
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
                "loaders": REGISTERED_LOADER if loaders is None else loaders,
                "version": "V4",
            }
        )
    )


def saved_config(config_file: Path) -> LatestConfig:
    return LatestConfig.model_validate_json(config_file.read_text())
