import datetime as dt

import pytest
from ynab import TransactionClearedStatus

from tests.factories import (
    DEFAULT_DATE,
    TransactionDetailFactory,
    TransactionWithYnabDataFactory,
)
from ynab_unlinked.config import ConfigV2
from ynab_unlinked.matcher import match_transactions
from ynab_unlinked.models import MatchStatus

pytestmark = pytest.mark.version("V2")

CLEARED = TransactionClearedStatus.CLEARED
UNCLEARED = TransactionClearedStatus.UNCLEARED
RECONCILED = TransactionClearedStatus.RECONCILED


def days(offset: int) -> dt.date:
    return DEFAULT_DATE + dt.timedelta(days=offset)


@pytest.mark.parametrize(
    "offset",
    [
        pytest.param(-11, id="eleven days early is out of the window"),
        pytest.param(-10, id="ten days early is the earliest accepted"),
        pytest.param(-1, id="the day before"),
        pytest.param(0, id="the same day"),
        pytest.param(1, id="the day after"),
        pytest.param(10, id="ten days late is the latest accepted"),
        pytest.param(11, id="eleven days late is out of the window"),
    ],
)
def test_matching_window_is_ten_days_either_side(offset: int, config_v2: ConfigV2):
    transaction = TransactionWithYnabDataFactory()

    match_transactions(
        [transaction],
        [TransactionDetailFactory(var_date=days(offset))],
        reconcile=False,
        config=config_v2,
    )

    assert (transaction.ynab_id == "ynab-1") is (abs(offset) <= 10)


@pytest.mark.parametrize(
    ("amount", "milliunits", "expected"),
    [
        pytest.param(-10.0, -10000, True, id="the same outflow matches"),
        pytest.param(-10.0, 10000, False, id="an inflow never matches an outflow"),
        pytest.param(10.0, -10000, False, id="an outflow never matches an inflow"),
        pytest.param(-12.345, -12345, True, id="three decimals are kept as milliunits"),
        pytest.param(-12.345, -12340, False, id="half a cent apart is not the same transaction"),
        pytest.param(-10.0, -10010, False, id="a cent apart is not the same transaction"),
        pytest.param(0.1 + 0.2, 300, True, id="a float that cannot be represented is rounded"),
    ],
)
def test_amount_must_match_to_the_milliunit_including_sign(
    amount: float, milliunits: int, expected: bool, config_v2: ConfigV2
):
    transaction = TransactionWithYnabDataFactory(amount=amount)

    match_transactions(
        [transaction],
        [TransactionDetailFactory(amount=milliunits)],
        reconcile=False,
        config=config_v2,
    )

    assert (transaction.ynab_id is not None) is expected


@pytest.mark.parametrize(
    ("bank_payee", "ynab_payee", "expected"),
    [
        pytest.param(
            "COMPRA EN MERCADONA 4412",
            "Mercadona",
            MatchStatus.MATCHED,
            id="a recognisable payee is a full match",
        ),
        pytest.param(
            "Something weird",
            "My Payee",
            MatchStatus.MATCHED,
            id="a configured rename rule is a full match",
        ),
        pytest.param(
            "Mercadona",
            "Zara",
            MatchStatus.PARTIAL_MATCH,
            id="an unrelated payee is only a partial match",
        ),
    ],
)
def test_the_payee_decides_whether_a_match_is_full_or_partial(
    bank_payee: str, ynab_payee: str, expected: MatchStatus, config_v2: ConfigV2
):
    transaction = TransactionWithYnabDataFactory(payee=bank_payee)
    candidate = TransactionDetailFactory(payee_name=ynab_payee)

    match_transactions([transaction], [candidate], reconcile=False, config=config_v2)

    assert transaction.match_status is expected
    assert transaction.partial_match is candidate
    assert transaction.ynab_id == "ynab-1"


def test_an_unmatched_transaction_is_left_untouched(config_v2: ConfigV2):
    transaction = TransactionWithYnabDataFactory()

    match_transactions(
        [transaction],
        [TransactionDetailFactory(var_date=days(30))],
        reconcile=False,
        config=config_v2,
    )

    assert transaction.match_status is MatchStatus.UNMATCHED
    assert transaction.ynab_id is None
    assert transaction.partial_match is None
    assert transaction.ynab_cleared is None


def test_the_candidate_closest_in_date_wins(config_v2: ConfigV2):
    transaction = TransactionWithYnabDataFactory()
    candidates = [
        TransactionDetailFactory(id="far", var_date=days(-8)),
        TransactionDetailFactory(id="near", var_date=days(2)),
        TransactionDetailFactory(id="middle", var_date=days(-5)),
    ]

    match_transactions([transaction], candidates, reconcile=False, config=config_v2)

    assert transaction.ynab_id == "near"


def test_date_proximity_beats_an_exact_payee_on_a_further_candidate(config_v2: ConfigV2):
    # Pins the documented trade-off in matcher.py:46: only date distance ranks candidates, so a
    # nearer transaction with an unrelated payee is preferred and only reaches PARTIAL_MATCH.
    transaction = TransactionWithYnabDataFactory(payee="Mercadona")
    candidates = [
        TransactionDetailFactory(id="exact-payee", payee_name="Mercadona", var_date=days(4)),
        TransactionDetailFactory(id="near", payee_name="Zara", var_date=days(1)),
    ]

    match_transactions([transaction], candidates, reconcile=False, config=config_v2)

    assert transaction.ynab_id == "near"
    assert transaction.match_status is MatchStatus.PARTIAL_MATCH


@pytest.mark.parametrize(
    ("candidate_ids", "expected"),
    [
        pytest.param(
            ["ynab-1"],
            {"ynab-1", None},
            id="one ynab transaction can only absorb one of the duplicates",
        ),
        pytest.param(
            ["ynab-1", "ynab-2"],
            {"ynab-1", "ynab-2"},
            id="two ynab transactions absorb both duplicates",
        ),
    ],
)
def test_identical_imports_never_share_one_ynab_transaction(
    candidate_ids: list[str], expected: set[str | None], config_v2: ConfigV2
):
    first = TransactionWithYnabDataFactory()
    second = TransactionWithYnabDataFactory()
    candidates = [TransactionDetailFactory(id=candidate_id) for candidate_id in candidate_ids]

    match_transactions([first, second], candidates, reconcile=False, config=config_v2)

    assert {first.ynab_id, second.ynab_id} == expected


def test_the_oldest_import_claims_a_shared_candidate_first(config_v2: ConfigV2):
    older = TransactionWithYnabDataFactory(date=days(-5))
    newer = TransactionWithYnabDataFactory(date=days(5))
    shared = TransactionDetailFactory(var_date=days(-4))

    match_transactions([newer, older], [shared], reconcile=False, config=config_v2)

    assert older.ynab_id == "ynab-1"
    assert newer.ynab_id is None


def test_an_import_id_hit_matches_fully_whatever_the_payee_and_date(config_v2: ConfigV2):
    transaction = TransactionWithYnabDataFactory(payee="Mercadona")
    previously_imported = TransactionDetailFactory(
        payee_name="Zara", var_date=days(90), amount=-999999, import_id=transaction.id
    )

    match_transactions([transaction], [previously_imported], reconcile=False, config=config_v2)

    assert transaction.ynab_id == "ynab-1"
    assert transaction.match_status is MatchStatus.MATCHED


def test_an_import_id_hit_is_preferred_over_a_closer_candidate(config_v2: ConfigV2):
    transaction = TransactionWithYnabDataFactory()
    candidates = [
        TransactionDetailFactory(id="same-day"),
        TransactionDetailFactory(id="previous-import", var_date=days(-6), import_id=transaction.id),
    ]

    match_transactions([transaction], candidates, reconcile=False, config=config_v2)

    assert transaction.ynab_id == "previous-import"


def test_an_import_id_already_taken_falls_back_to_date_and_amount(config_v2: ConfigV2):
    # Both imports hash to the same id, so they point at the same YNAB import_id. The second one
    # must still find its own counterpart instead of silently going unmatched.
    first = TransactionWithYnabDataFactory()
    second = TransactionWithYnabDataFactory()
    assert first.id == second.id
    candidates = [
        TransactionDetailFactory(id="previous-import", import_id=first.id),
        TransactionDetailFactory(id="plain", var_date=days(1)),
    ]

    match_transactions([first, second], candidates, reconcile=False, config=config_v2)

    assert first.ynab_id == "previous-import"
    assert second.ynab_id == "plain"


@pytest.mark.parametrize(
    ("ynab_cleared", "reconcile", "expected_cleared"),
    [
        pytest.param(UNCLEARED, False, CLEARED, id="an uncleared counterpart is cleared by us"),
        pytest.param(CLEARED, False, CLEARED, id="a cleared counterpart stays cleared"),
        pytest.param(RECONCILED, False, RECONCILED, id="a reconciled counterpart reconciles us"),
        pytest.param(CLEARED, True, RECONCILED, id="the reconcile flag reconciles the match"),
    ],
)
def test_a_match_records_the_previous_ynab_state_and_updates_the_cleared_status(
    ynab_cleared: TransactionClearedStatus,
    reconcile: bool,
    expected_cleared: TransactionClearedStatus,
    config_v2: ConfigV2,
):
    transaction = TransactionWithYnabDataFactory()

    match_transactions(
        [transaction], [TransactionDetailFactory(cleared=ynab_cleared)], reconcile, config=config_v2
    )

    assert transaction.ynab_cleared is ynab_cleared
    assert transaction.cleared is expected_cleared
