from __future__ import annotations

import datetime as dt
from unittest.mock import MagicMock

import pytest
from ynab import TransactionClearedStatus

from tests.factories import (
    DEFAULT_DATE,
    TransactionDetailFactory,
    TransactionWithYnabDataFactory,
)
from tests.utils.builders import column, only_table, styles
from ynab_unlinked.formatter import Formatter
from ynab_unlinked.models import MatchStatus, TransactionWithYnabData
from ynab_unlinked.utils import (
    display_partial_matches,
    display_transactions_to_upload,
    payee_line,
    updload_help_message,
)

UNCLEARED_IN_YNAB = TransactionDetailFactory(cleared=TransactionClearedStatus.UNCLEARED)


@pytest.mark.parametrize(
    "transaction, expected",
    [
        pytest.param(
            TransactionWithYnabDataFactory(
                status=MatchStatus.MATCHED, payee="Mercadona", ynab_payee="Mercadona"
            ),
            "Mercadona",
            id="an unchanged payee is shown once",
        ),
        pytest.param(
            TransactionWithYnabDataFactory(
                status=MatchStatus.MATCHED, payee="MERCADONA SL", ynab_payee="Mercadona"
            ),
            "Mercadona [gray37] [Original payee: MERCADONA SL][/gray37]",
            id="a renamed payee keeps the original visible",
        ),
    ],
)
def test_payee_line(transaction: TransactionWithYnabData, expected: str):
    assert payee_line(transaction) == expected


@pytest.mark.xfail(
    reason=(
        "utils.py:136 interpolates a None ynab_payee, so a YNAB partial match without a payee "
        "name renders the literal 'None' instead of the imported payee"
    ),
    strict=True,
)
def test_payee_line_without_a_ynab_payee_falls_back_to_the_imported_payee():
    transaction = TransactionWithYnabDataFactory(status=MatchStatus.MATCHED, payee="Mercadona")
    transaction.ynab_payee = None

    assert payee_line(transaction) == "Mercadona"


@pytest.mark.parametrize("with_partial_matches", [True, False])
def test_upload_help_message_explains_yellow_rows_only_when_there_are_partial_matches(
    with_partial_matches: bool,
):
    message = updload_help_message(with_partial_matches)

    assert "[green]green[/]" in message
    assert "cleared status column" in message
    assert ("[yellow]yellow[/]" in message) is with_partial_matches


def test_nothing_is_displayed_when_there_is_nothing_to_upload(
    printed: MagicMock, formatter: Formatter
):
    display_transactions_to_upload([], formatter)

    printed.assert_not_called()


@pytest.mark.parametrize(
    "transaction, expected_style, expected_emoji",
    [
        pytest.param(
            TransactionWithYnabDataFactory(status=MatchStatus.UNMATCHED),
            "green",
            "",
            id="a new transaction is green",
        ),
        pytest.param(
            TransactionWithYnabDataFactory(
                status=MatchStatus.PARTIAL_MATCH, partial_match=UNCLEARED_IN_YNAB
            ),
            "yellow",
            "🔍",
            id="a partial match still to import is yellow",
        ),
        pytest.param(
            TransactionWithYnabDataFactory(status=MatchStatus.MATCHED),
            "default",
            "🔗",
            id="a transaction already in ynab is plain",
        ),
    ],
)
def test_upload_table_styles_rows_by_what_will_happen_to_them(
    printed: MagicMock,
    formatter: Formatter,
    transaction: TransactionWithYnabData,
    expected_style: str,
    expected_emoji: str,
):
    display_transactions_to_upload([transaction], formatter)

    table = only_table(printed)
    assert styles(table) == [expected_style]
    assert column(table, "Match") == [expected_emoji]


def test_upload_table_help_mentions_partial_matches_when_one_is_listed(
    printed: MagicMock, formatter: Formatter
):
    display_transactions_to_upload(
        [
            TransactionWithYnabDataFactory(status=MatchStatus.UNMATCHED),
            TransactionWithYnabDataFactory(
                status=MatchStatus.PARTIAL_MATCH,
                payee="Bakery",
                partial_match=TransactionDetailFactory(
                    payee_name="Bakery Ltd", cleared=TransactionClearedStatus.UNCLEARED
                ),
            ),
        ],
        formatter,
    )

    help_message = next(
        call.args[0] for call in printed.call_args_list if isinstance(call.args[0], str)
    )
    assert "[yellow]yellow[/]" in help_message


def test_partial_matches_table_pairs_the_imported_and_the_ynab_transaction(
    printed: MagicMock, formatter: Formatter
):
    display_partial_matches(
        [
            TransactionWithYnabDataFactory(
                status=MatchStatus.PARTIAL_MATCH,
                payee="MERCADONA SL",
                amount=-12.34,
                partial_match=TransactionDetailFactory(
                    payee_name="Mercadona",
                    amount=-12340,
                    var_date=DEFAULT_DATE + dt.timedelta(days=1),
                    cleared=TransactionClearedStatus.UNCLEARED,
                ),
            )
        ],
        formatter,
    )

    table = only_table(printed)
    assert column(table, "Date") == ["15/05/2025", "16/05/2025"]
    assert column(table, "Payee") == ["MERCADONA SL", "Mercadona"]
    assert column(table, "Outflow") == ["-12.34€", "-12.34€"]
    assert column(table, "Cleared Status") == ["✅ Cleared", "Uncleared"]
    assert [row.end_section for row in table.rows] == [False, True]


def test_partial_matches_table_shows_an_inflow_for_a_positive_ynab_amount(
    printed: MagicMock, formatter: Formatter
):
    display_partial_matches(
        [
            TransactionWithYnabDataFactory(
                status=MatchStatus.PARTIAL_MATCH,
                amount=12.34,
                partial_match=TransactionDetailFactory(
                    amount=12340, cleared=TransactionClearedStatus.UNCLEARED
                ),
            )
        ],
        formatter,
    )

    table = only_table(printed)
    assert column(table, "Inflow") == ["12.34€", "12.34€"]
    assert column(table, "Outflow") == ["", ""]


@pytest.mark.parametrize(
    "transaction",
    [
        pytest.param(
            TransactionWithYnabDataFactory(
                status=MatchStatus.PARTIAL_MATCH, partial_match=TransactionDetailFactory()
            ),
            id="the partial match is already cleared in ynab",
        ),
        pytest.param(
            TransactionWithYnabDataFactory(status=MatchStatus.UNMATCHED),
            id="there is no partial match",
        ),
        pytest.param(
            TransactionWithYnabDataFactory(status=MatchStatus.PARTIAL_MATCH, partial_match=None),
            id="the partial status has no transaction behind it",
        ),
    ],
)
def test_partial_matches_table_only_lists_transactions_that_will_be_imported(
    printed: MagicMock, formatter: Formatter, transaction: TransactionWithYnabData
):
    display_partial_matches([transaction], formatter)

    assert only_table(printed).row_count == 0
