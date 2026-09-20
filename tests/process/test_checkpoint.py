import datetime as dt
from pathlib import Path

import pytest

from tests.factories import TransactionDetailFactory, TransactionFactory
from tests.helpers.types import CliRunner, LoadEntityCallback
from tests.helpers.ynab_api import YnabClientStub
from tests.process.builders import (
    FIVE_DAYS_AGO,
    THREE_DAYS_AGO,
    TODAY,
    YESTERDAY,
    saved_config,
)

pytestmark = pytest.mark.version("V2")


def test_an_aborted_load_leaves_the_checkpoint_untouched(
    config_file: Path, yul: CliRunner, load_entity: LoadEntityCallback, ynab: YnabClientStub
):
    load_entity(TODAY, [TransactionFactory(date=THREE_DAYS_AGO)])

    result = yul("load test", input="n\n")

    assert result.exit_code == 0, result.output
    assert saved_config(config_file).entities["test"].checkpoint is None


def test_a_load_with_nothing_to_do_still_moves_the_checkpoint(
    config_file: Path,
    yul: CliRunner,
    load_entity: LoadEntityCallback,
    existing_in_ynab,
):
    imported = TransactionFactory(date=THREE_DAYS_AGO)
    existing_in_ynab([TransactionDetailFactory(var_date=THREE_DAYS_AGO, import_id=imported.id)])
    load_entity(TODAY, [imported])

    result = yul("load test")

    assert result.exit_code == 0, result.output
    assert saved_config(config_file).entities["test"].checkpoint is not None


@pytest.mark.xfail(
    reason=(
        "process.py:206 checkpoints transactions[0], and match_transactions sorted the list by "
        "date, so the checkpoint records the earliest processed date instead of the latest"
    ),
    strict=True,
)
def test_the_checkpoint_records_the_latest_processed_date(
    config_file: Path, yul: CliRunner, load_entity: LoadEntityCallback, ynab: YnabClientStub
):
    load_entity(
        TODAY,
        [
            TransactionFactory(date=FIVE_DAYS_AGO, payee="Coffee Shop"),
            TransactionFactory(date=YESTERDAY, payee="Bakery"),
        ],
    )

    result = yul("load test", input="y\n")

    assert result.exit_code == 0, result.output
    checkpoint = saved_config(config_file).entities["test"].checkpoint
    assert checkpoint is not None
    # The stored date is the latest one minus the two day grace period
    assert checkpoint.latest_date_processed == YESTERDAY - dt.timedelta(days=2)
