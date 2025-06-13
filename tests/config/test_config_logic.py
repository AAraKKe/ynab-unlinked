import datetime as dt
import json
from collections.abc import Callable
from pathlib import Path

import pytest

from ynab_unlinked.config import Config
from ynab_unlinked.config.constants import TRANSACTION_GRACE_PERIOD_DAYS
from ynab_unlinked.models import Transaction

# This module tests the central logic of the config object. It does not focus on each particular
# version and instead ensures that the logic that needs to be supported is supported propertly


def record_save(output: list[str]) -> Callable:
    def save_output(self, value: str):
        nonlocal output
        output[0] = value
        return

    return save_output


def test_save(config_obj: Config, monkeypatch: pytest.MonkeyPatch):
    config_obj.api_key = "some-other-api-key"  # type: ignore
    output = [""]

    monkeypatch.setattr(Path, "write_text", record_save(output))

    config_obj.save()
    assert output[0] != ""

    content = json.loads(output[0])
    assert content["api_key"] == "some-other-api-key"


def test_update_and_save(config_obj: Config, monkeypatch: pytest.MonkeyPatch):
    trasaction_date = dt.date(2025, 1, 1)
    transaction = Transaction(date=trasaction_date, payee="Acme Store", amount=-12.34)
    output = [""]

    monkeypatch.setattr(Path, "write_text", record_save(output))

    config_obj.update_and_save(transaction, "sabadell")

    assert output[0] != ""

    sabadell = json.loads(output[0])["entities"]["sabadell"]
    assert dt.datetime.strptime(
        sabadell["checkpoint"]["latest_date_processed"], "%Y-%m-%d"
    ).date() == (trasaction_date - dt.timedelta(days=TRANSACTION_GRACE_PERIOD_DAYS))
