import datetime as dt

import pytest

from tests.helpers import assets
from ynab_unlinked.context_object import YnabUnlinkedContext
from ynab_unlinked.entities.bbva.bbva import BBVA

pytestmark = [pytest.mark.version("V2"), pytest.mark.usefixtures("config")]


def test_parse_xlsx(context_obj: YnabUnlinkedContext):
    transactions = BBVA().parse(assets.path("bbva/bbva.xlsx"), context_obj)

    assert len(transactions) == 17
    # Transaction 1 is July 11, Netflix.com for 19.99
    assert transactions[0].date == dt.date(2025, 7, 11)
    assert transactions[0].payee == "Netflix.com"
    assert transactions[0].amount == -19.99

    # Transaction 5 is a payment
    assert transactions[4].date == dt.date(2025, 7, 5)
    assert transactions[4].payee == "Recibo mes anterior"
    assert transactions[4].amount == 270.74
