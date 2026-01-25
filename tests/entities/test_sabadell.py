from pathlib import Path
from typing import cast

from ynab_unlinked.context_object import YnabUnlinkedContext
from ynab_unlinked.entities.sabadell.sabadell import ANCHOR_LINE, SabadellParser


def test_parse_txt_negative_amount(tmp_path: Path) -> None:
    # Setup
    # Note: Sabadell parser requires CP1252 encoding
    # We construct a file that mimics the structure expected by the parser
    # It waits for ANCHOR_LINE to start parsing
    content = f"""
Some Header Info
{ANCHOR_LINE}
25/01|TEST REFUND|SOMETHING|-10,50EUR
25/01|TEST PURCHASE|SOMETHING|20,00EUR
    """.strip()

    input_file = tmp_path / "sabadell.txt"
    input_file.write_text(content, encoding="cp1252")

    parser = SabadellParser(year=2024)
    # We can pass None as context since it's not used in __parse_txt
    transactions = parser.parse(input_file, cast(YnabUnlinkedContext, None))

    assert len(transactions) == 2

    assert transactions[0].payee == "Test Refund"
    assert transactions[0].amount == 10.50

    assert transactions[1].payee == "Test Purchase"
    assert transactions[1].amount == -20.00
