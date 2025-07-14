import datetime as dt

import pytest

from tests.helpers.types import CliRunner, LoadEntityCallback
from tests.helpers.ynab_api import YnabClientStub

pytestmark = pytest.mark.version("V2")


def test_load(
    yul: CliRunner,
    load_entity: LoadEntityCallback,
    today: dt.datetime,
    ynab_api: YnabClientStub,
):
    load_entity(today)
    result = yul("load --show test")
    assert result.exit_code == 0, f"Error found: {result.output_bytes}"
