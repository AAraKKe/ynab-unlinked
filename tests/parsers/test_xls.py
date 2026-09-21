from collections.abc import Sequence

import pytest

from tests.helpers import assets

STATEMENT = "parsers/statement.xls"
HEADER = ["FECHA", "CONCEPTO", "LOCALIDAD", "SIT. MOV.", "IMPORTE", "EUR"]
SECOND_HEADER_INDEX = 6


def payees(rows: Sequence[Sequence[str]]) -> list[str]:
    return [row[1] for row in rows]


def test_reading_starts_on_the_row_after_the_header():
    rows = list(assets.read_xls(STATEMENT, read_after_row_like=HEADER))

    assert rows == [
        ["29/06", "JustEat", "MADRID", "AUT", "26,90", "EUR"],
        ["", "", "TOTAL OPERACIONES", "", "", ""],
        HEADER,
        ["28/06", "Los Diamantes", "GRANADA", " ", "34,80", "EUR"],
    ]


@pytest.mark.parametrize(
    "header",
    [
        pytest.param(HEADER[:3], id="a-prefix-of-the-header-does-not-match"),
        pytest.param([*HEADER, "SALDO"], id="an-extra-column-does-not-match"),
        pytest.param(
            ["CONCEPTO", "FECHA", "LOCALIDAD", "SIT. MOV.", "IMPORTE", "EUR"],
            id="the-same-columns-in-another-order-do-not-match",
        ),
        pytest.param(["TOTAL OPERACIONES"], id="a-row-that-is-not-in-the-sheet-does-not-match"),
    ],
)
def test_nothing_is_read_when_no_row_matches_the_header_exactly(header: list[str]):
    assert list(assets.read_xls(STATEMENT, read_after_row_like=header)) == []


@pytest.mark.parametrize(
    ("header", "expected_payees"),
    [
        pytest.param(
            ["FECHA", "CONCEPTO", "LOCALIDAD"],
            ["JustEat", "", "CONCEPTO", "Los Diamantes"],
            id="the-leading-columns-are-enough-to-find-the-header",
        ),
        pytest.param(["FECHA", "LOCALIDAD"], [], id="the-columns-must-be-in-order"),
    ],
)
def test_a_partial_match_only_looks_at_the_leading_columns(
    header: list[str], expected_payees: list[str]
):
    """Sabadell writes two header variants that only share their first three columns."""
    rows = assets.read_xls(STATEMENT, read_after_row_like=header, allow_partial_match=True)

    assert payees(list(rows)) == expected_payees


def test_rows_skipped_by_read_after_row_cannot_trigger_the_header():
    """The header is repeated, so skipping rows is how the first one is left behind."""
    rows = assets.read_xls(
        STATEMENT, read_after_row=SECOND_HEADER_INDEX, read_after_row_like=HEADER
    )

    assert payees(list(rows)) == ["Los Diamantes"]


def test_read_after_row_on_its_own_yields_the_rows_that_follow():
    rows = assets.read_xls(STATEMENT, read_after_row=4)

    assert payees(list(rows)) == ["JustEat", "", "CONCEPTO", "Los Diamantes"]
