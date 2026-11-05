import datetime as dt
from uuid import UUID

import pytest
from ynab import TransactionClearedStatus

from tests.factories import AccountBalanceFactory
from tests.helpers.ynab_api import YnabClientStub
from ynab_unlinked.buckets import Bucket
from ynab_unlinked.core.balances import (
    Adjustment,
    DebtNetting,
    build_adjustments,
    create_adjustments,
    net_worth,
    parse_amount_to_milliunits,
)
from ynab_unlinked.ynab_api import Client

BUDGET_ID = "00000000-0000-0000-0000-000000000001"
CHECKING = "00000000-0000-0000-0000-00000000000a"
SAVINGS = "00000000-0000-0000-0000-00000000000b"


def household(card_balance: int):
    """A checking, a savings, a house and a credit card owing `card_balance` milliunits."""
    return [
        AccountBalanceFactory(id="checking", balance=10_000),
        AccountBalanceFactory(id="savings", bucket=Bucket.SAVINGS, balance=10_000),
        AccountBalanceFactory(id="house", bucket=Bucket.ASSETS, balance=10_000),
        AccountBalanceFactory(id="card", bucket=Bucket.DEBT, balance=card_balance),
    ]


def balances(accounts) -> dict[str, int]:
    return {a.id: a.balance for a in accounts}


@pytest.mark.parametrize(
    ("card_balance", "mapped_to", "expected", "unnetted"),
    [
        pytest.param(
            -900,
            ("checking", "savings", "house"),
            {"checking": 9_700, "savings": 9_700, "house": 9_700},
            0,
            id="an even split",
        ),
        pytest.param(
            -1_000,
            ("checking", "savings", "house"),
            {"checking": 9_666, "savings": 9_667, "house": 9_667},
            0,
            id="the remainder lands on the first mapped account",
        ),
        pytest.param(
            -1_001,
            ("savings", "checking"),
            # The split truncates toward zero, so the first account takes the extra unit
            {"checking": 9_500, "savings": 9_499, "house": 10_000},
            0,
            id="an odd split truncates toward zero",
        ),
        pytest.param(
            -1_000,
            (),
            {"checking": 10_000, "savings": 10_000, "house": 10_000},
            -1_000,
            id="an unmapped debt still comes off the total",
        ),
        pytest.param(
            -1_000,
            ("card", "missing", "checking"),
            {"checking": 9_667, "savings": 10_000, "house": 10_000},
            # The first share takes the remainder: -334 (card) and -333 (missing)
            -667,
            id="shares for debt or unknown accounts still come off the total",
        ),
    ],
)
def test_net_worth_nets_each_debt_over_its_mapped_accounts(
    card_balance: int, mapped_to: tuple[str, ...], expected: dict[str, int], unnetted: int
):
    result = net_worth(household(card_balance), [DebtNetting("card", mapped_to)])

    assert balances(result.accounts) == {**expected, "card": card_balance}
    assert result.unnetted == unnetted
    # Every debt is in the total exactly once, netted or not
    assert result.total == sum(expected.values()) + unnetted == 30_000 + card_balance


def test_net_worth_ignores_nettings_for_accounts_that_are_not_debt():
    accounts = household(-1_000)

    result = net_worth(accounts, [DebtNetting("savings", ("checking",))])

    assert balances(result.accounts) == balances(accounts)
    # The card has no mapping of its own: not netted, still off the total
    assert result.total == 29_000


def test_by_bucket_totals_the_netted_balances_and_keeps_debt_raw():
    accounts = [
        *household(-3_000),
        AccountBalanceFactory(id="wallet", balance=500),
        AccountBalanceFactory(id="loan", bucket=Bucket.DEBT, balance=-50_000),
    ]

    result = net_worth(accounts, [DebtNetting("card", ("checking", "wallet"))])

    assert result.by_bucket() == {
        Bucket.CASH: 10_000 + 500 - 3_000,
        Bucket.SAVINGS: 10_000,
        Bucket.ASSETS: 10_000,
        Bucket.DEBT: -53_000,
    }


def test_by_bucket_reports_empty_buckets_as_zero():
    result = net_worth([AccountBalanceFactory(balance=1_000)], [])

    assert result.by_bucket() == {
        Bucket.CASH: 1_000,
        Bucket.SAVINGS: 0,
        Bucket.ASSETS: 0,
        Bucket.DEBT: 0,
    }


def test_share_is_the_netted_balance_over_the_total():
    result = net_worth(household(-6_000), [DebtNetting("card", ("checking",))])

    assert result.total == 24_000
    assert result.share("checking") == pytest.approx(4_000 / 24_000)
    assert result.share("savings") == pytest.approx(10_000 / 24_000)
    assert result.share("card") == 0.0


def test_share_is_zero_when_there_is_no_net_worth():
    result = net_worth(
        [
            AccountBalanceFactory(id="checking", balance=1_000),
            AccountBalanceFactory(id="card", bucket=Bucket.DEBT, balance=-1_000),
        ],
        [DebtNetting("card", ("checking",))],
    )

    assert result.share("checking") == 0.0


def test_share_of_an_unknown_account_is_an_error():
    with pytest.raises(KeyError, match="missing"):
        net_worth(household(0), []).share("missing")


def test_build_adjustments_only_for_balances_that_changed():
    current = {"checking": 10_000, "savings": 5_000, "house": 200_000}
    wanted = {"house": 190_000, "checking": 10_000, "savings": 5_250}

    adjustments = build_adjustments(current, wanted)

    assert [(a.account_id, a.amount) for a in adjustments] == [
        ("house", -10_000),
        ("savings", 250),
    ]


def test_build_adjustments_needs_a_current_balance_for_every_wanted_one():
    with pytest.raises(KeyError, match="savings"):
        build_adjustments({"checking": 0}, {"savings": 100})


@pytest.fixture
def client(ynab_api: YnabClientStub) -> Client:
    return Client(api_key="an-api-key")


def test_create_adjustments_sends_one_approved_transaction_per_adjustment(
    client: Client, ynab_api: YnabClientStub
):
    api = ynab_api.api("transactions")
    api.create_transaction.return_value.data.transaction_ids = ["t-1", "t-2"]
    adjustments = [
        Adjustment(account_id=CHECKING, old_balance=10_000, new_balance=12_500),
        Adjustment(account_id=SAVINGS, old_balance=10_000, new_balance=9_000),
    ]

    created = create_adjustments(
        client,
        BUDGET_ID,
        adjustments,
        memo="Balance adjustment by yul",
        payee="Balance Adjustment",
        cleared=TransactionClearedStatus.RECONCILED,
        date=dt.date(2025, 5, 15),
    )

    assert created == 2
    call = api.create_transaction.call_args
    assert call.args == (BUDGET_ID,)
    sent = call.kwargs["data"].transactions
    assert [(t.account_id, t.amount) for t in sent] == [
        (UUID(CHECKING), 2_500),
        (UUID(SAVINGS), -1_000),
    ]
    for transaction in sent:
        assert transaction.var_date == dt.date(2025, 5, 15)
        assert transaction.memo == "Balance adjustment by yul"
        assert transaction.payee_name == "Balance Adjustment"
        assert transaction.cleared == TransactionClearedStatus.RECONCILED
        # Adjustments are the user's own figures: nothing to review, nothing to dedupe on
        assert transaction.approved is True
        assert transaction.import_id is None


def test_create_adjustments_does_not_reach_ynab_with_nothing_to_adjust(
    client: Client, ynab_api: YnabClientStub
):
    created = create_adjustments(
        client,
        BUDGET_ID,
        [],
        memo="memo",
        payee="payee",
        cleared=TransactionClearedStatus.CLEARED,
        date=dt.date(2025, 5, 15),
    )

    assert created == 0
    assert ynab_api.registry == {}


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        pytest.param("100", 100_000, id="positive_integer"),
        pytest.param("123.45", 123_450, id="positive_float"),
        pytest.param("123.4", 123_400, id="positive_float_single_decimal"),
        pytest.param("12.3456", 12_346, id="positive_float_many_decimals"),
        pytest.param("-50", -50_000, id="negative_integer"),
        pytest.param("-123.45", -123_450, id="negative_float"),
        pytest.param("-123.4", -123_400, id="negative_float_single_decimal"),
        pytest.param("0", 0, id="zero_integer"),
        pytest.param("0.00", 0, id="zero_float"),
        pytest.param("$100.50", 100_500, id="currency_symbol"),
        pytest.param("1,234.56", 1_234_560, id="commas"),
        pytest.param("$1,234.56", 1_234_560, id="commas_and_symbol"),
        pytest.param("-$1,234.56", -1_234_560, id="negative_commas_and_symbol"),
        pytest.param(".50", 500, id="leading_decimal"),
        pytest.param(".5", 500, id="leading_decimal_single_digit"),
        pytest.param("50.", 50_000, id="trailing_decimal"),
        pytest.param("  123.45  ", 123_450, id="whitespace"),
        pytest.param("  - $ 1,234.56 ", -1_234_560, id="whitespace_and_symbols"),
        pytest.param("+€50", 50_000, id="leading_plus_and_euro"),
        pytest.param("---$700", -700_000, id="repeated_minus_signs"),
        pytest.param("US$12.50", 12_500, id="symbol_after_letters"),
        pytest.param("1,234,567.891", 1_234_567_891, id="several_groups"),
        pytest.param("0.0005", 1, id="half_a_milliunit_rounds_up"),
        # Read as 1,234 before: a typo for 12.34 must not write a balance 100 times too big
        pytest.param("12,34", None, id="a_group_of_two_digits"),
        pytest.param("€99,99", None, id="comma_decimals_in_a_dot_budget"),
        pytest.param("1,2345", None, id="a_group_of_four_digits"),
        pytest.param("50,", None, id="a_trailing_group_separator"),
        pytest.param("1e5", None, id="scientific_notation"),
        pytest.param("12abc", None, id="letters_that_are_no_currency"),
        pytest.param("100 dollars", None, id="a_currency_name"),
        pytest.param("EUR 5 USD", None, id="two_currencies"),
        pytest.param("1_000", None, id="an_underscore"),
        pytest.param("abc", None, id="invalid_alpha"),
        pytest.param("", None, id="invalid_empty"),
        pytest.param("$", None, id="invalid_just_symbol"),
        pytest.param("-", None, id="invalid_just_minus"),
        pytest.param("1.2.3", None, id="invalid_multiple_decimals"),
        pytest.param("-+10", None, id="invalid_mixed_signs"),
        pytest.param("1+2-3", None, id="invalid_signs_between_digits"),
    ],
)
def test_parse_amount_to_milliunits(text: str, expected: int | None):
    assert parse_amount_to_milliunits(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        pytest.param("1.000,50", 1_000_500, id="group_and_decimal"),
        pytest.param("99,99", 99_990, id="comma_decimal"),
        pytest.param("1.234.567,8", 1_234_567_800, id="several_groups"),
        pytest.param("1.000", 1_000_000, id="dot_is_a_group_separator"),
        pytest.param(",5", 500, id="leading_decimal"),
        pytest.param("-1.234,56", -1_234_560, id="negative"),
        pytest.param("1.000,50 €", 1_000_500, id="trailing_euro"),
        pytest.param("€ 1.000,50", 1_000_500, id="leading_euro"),
        pytest.param("EUR -12,30", -12_300, id="leading_iso_code"),
        pytest.param("12,30 EUR", 12_300, id="trailing_iso_code"),
        pytest.param("€1.000,50", 1_000_500, id="leading_euro_without_space"),
        pytest.param("1,2,3", None, id="invalid_multiple_decimals"),
        pytest.param("1.5", None, id="a_dot_that_is_no_group_of_three"),
        pytest.param("1,234.56", None, id="dot_decimals_in_a_comma_budget"),
        pytest.param(".5", None, id="a_dot_where_the_decimal_comma_goes"),
    ],
)
def test_parse_amount_with_comma_decimals(text: str, expected: int | None):
    assert parse_amount_to_milliunits(text, decimal_separator=",", group_separator=".") == expected


@pytest.mark.parametrize(
    "text",
    [
        pytest.param("1500", id="bare"),
        pytest.param("€1500", id="leading_symbol"),
        pytest.param("1500 EUR", id="trailing_iso_code"),
        pytest.param("$ 1500", id="leading_dollar"),
    ],
)
@pytest.mark.parametrize(
    ("decimal_separator", "group_separator"),
    [pytest.param(".", ",", id="dot_decimal"), pytest.param(",", ".", id="comma_decimal")],
)
def test_a_number_without_separators_reads_the_same_with_any_separators(
    text: str, decimal_separator: str, group_separator: str
):
    parsed = parse_amount_to_milliunits(
        text, decimal_separator=decimal_separator, group_separator=group_separator
    )

    assert parsed == 1_500_000


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        pytest.param("1 000,50", 1_000_500, id="space_group"),
        pytest.param("1 000", 1_000_000, id="space_group_no_decimals"),
        pytest.param("1 000,50 €", 1_000_500, id="space_group_and_trailing_symbol"),
    ],
)
def test_a_group_separator_that_is_not_a_dot_or_comma_is_read_between_digits(
    text: str, expected: int
):
    assert parse_amount_to_milliunits(text, decimal_separator=",", group_separator=" ") == expected


@pytest.mark.parametrize(
    ("decimal_separator", "group_separator"),
    [pytest.param(";", ",", id="unknown_decimal"), pytest.param(",", ",", id="same_separator")],
)
def test_unusable_separators_are_rejected(decimal_separator: str, group_separator: str):
    with pytest.raises(ValueError, match="separator"):
        parse_amount_to_milliunits(
            "1", decimal_separator=decimal_separator, group_separator=group_separator
        )
