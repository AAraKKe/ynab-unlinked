import datetime as dt

import pytest
from ynab import TransactionClearedStatus

from tests.factories import (
    TransactionDetailFactory,
    TransactionFactory,
    TransactionWithYnabDataFactory,
)
from ynab_unlinked.models import MatchStatus, TransactionWithYnabData

CLEARED = TransactionClearedStatus.CLEARED
UNCLEARED = TransactionClearedStatus.UNCLEARED
RECONCILED = TransactionClearedStatus.RECONCILED


def matched(
    ynab_cleared: TransactionClearedStatus | None,
    status: MatchStatus,
) -> TransactionWithYnabData:
    transaction = TransactionWithYnabDataFactory()
    transaction.match_status = status
    if ynab_cleared is not None:
        transaction.partial_match = TransactionDetailFactory(cleared=ynab_cleared)
        transaction.ynab_cleared = ynab_cleared
    return transaction


@pytest.mark.parametrize(
    ("payee", "expected"),
    [
        pytest.param("Mercadona", "Mercadona", id="a short payee is shown in full"),
        pytest.param("A" * 14, "A" * 14, id="fourteen characters still fit"),
        pytest.param("A" * 16, f"{'A' * 15}...", id="sixteen characters are cut to fifteen"),
        pytest.param(
            "Supermercado Rio Grande",
            "Supermercado Ri...",
            id="a long payee keeps its first fifteen characters",
        ),
    ],
)
def test_pretty_payee_truncates_long_payees(payee: str, expected: str):
    assert TransactionFactory(payee=payee).pretty_payee == expected


@pytest.mark.xfail(
    reason=(
        "models.py:30 truncates whenever len(payee) >= 15, so a payee of exactly 15 characters "
        "is replaced by all 15 of its characters plus an ellipsis, which is longer than the "
        "original and falsely suggests the name was cut"
    ),
    strict=True,
)
def test_pretty_payee_leaves_a_fifteen_character_payee_alone():
    payee = "Supermercado 24"
    assert len(payee) == 15
    assert TransactionFactory(payee=payee).pretty_payee == payee


def test_id_is_stable_across_runs():
    # The id is uploaded to YNAB as import_id. If the digest ever changes, every previously
    # imported transaction would be re-created as a duplicate on the next import.
    assert TransactionFactory(amount=-10.5).id == "14110f975124ca05a3a2feeb647145"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        pytest.param("counter", 1, id="a duplicate of the same row gets its own id"),
        pytest.param("date", dt.date(2025, 5, 16), id="a different date is a different id"),
        pytest.param("payee", "Carrefour", id="a different payee is a different id"),
        pytest.param("amount", -10.51, id="a different amount is a different id"),
    ],
)
def test_id_changes_when_an_identifying_field_changes(field: str, value: object):
    original = TransactionFactory(amount=-10.5)
    changed = TransactionFactory(amount=-10.5)
    setattr(changed, field, value)

    assert original.id != changed.id


def test_hash_ignores_the_duplicate_counter():
    # The counter only disambiguates import ids. Two duplicated rows of the same export are
    # still equal transactions, so they must not drift apart as dict or set keys.
    first = TransactionFactory(amount=-10.5)
    second = TransactionFactory(amount=-10.5)
    second.counter = 1

    assert first == second
    assert hash(first) == hash(second)


@pytest.mark.xfail(
    reason=(
        "models.py:57-62 rebuilds the base Transaction, so __post_init__ resets past and counter. "
        "process.preprocess_transactions assigns the counter before wrapping, so duplicated rows "
        "of the same export all end up with counter 0 and therefore the same import_id"
    ),
    strict=True,
)
def test_wrapping_keeps_the_duplicate_counter():
    duplicate = TransactionFactory(amount=-10.5)
    duplicate.counter = 1
    duplicate.past = True

    wrapped = TransactionWithYnabData(duplicate)

    assert wrapped.counter == 1
    assert wrapped.past is True
    assert wrapped.id == duplicate.id


@pytest.mark.parametrize(
    ("status", "ynab_cleared", "expected"),
    [
        pytest.param(
            MatchStatus.UNMATCHED, None, True, id="an unmatched transaction has to be created"
        ),
        pytest.param(
            MatchStatus.MATCHED, CLEARED, False, id="a match against a cleared one is already there"
        ),
        pytest.param(
            MatchStatus.MATCHED,
            RECONCILED,
            False,
            id="a match against a reconciled one is already there",
        ),
        pytest.param(
            MatchStatus.MATCHED,
            UNCLEARED,
            True,
            id="a match against an uncleared one is re-sent to clear it",
        ),
        pytest.param(
            MatchStatus.PARTIAL_MATCH, CLEARED, False, id="a cleared partial match is already there"
        ),
        pytest.param(
            MatchStatus.PARTIAL_MATCH, UNCLEARED, True, id="an uncleared partial match is re-sent"
        ),
    ],
)
def test_needs_creation(
    status: MatchStatus, ynab_cleared: TransactionClearedStatus | None, expected: bool
):
    assert matched(ynab_cleared, status).needs_creation is expected


@pytest.mark.parametrize(
    ("status", "ynab_cleared", "expected"),
    [
        pytest.param(
            MatchStatus.MATCHED,
            RECONCILED,
            "🔒 Reconciled",
            id="a transaction that will not be recreated shows its ynab status",
        ),
        pytest.param(
            MatchStatus.MATCHED,
            UNCLEARED,
            "✅ Cleared",
            id="a transaction that will be recreated shows the status we are about to send",
        ),
        pytest.param(
            MatchStatus.UNMATCHED,
            None,
            "✅ Cleared",
            id="an unmatched transaction shows the imported status",
        ),
    ],
)
def test_cleared_status(
    status: MatchStatus, ynab_cleared: TransactionClearedStatus | None, expected: str
):
    assert matched(ynab_cleared, status).cleared_status == expected


@pytest.mark.parametrize(
    ("ynab_cleared", "expected"),
    [
        pytest.param(None, "", id="nothing is shown when there is no ynab counterpart"),
        pytest.param(CLEARED, "✅ Cleared", id="a cleared counterpart"),
        pytest.param(UNCLEARED, "Uncleared", id="an uncleared counterpart"),
        pytest.param(RECONCILED, "🔒 Reconciled", id="a reconciled counterpart"),
    ],
)
def test_ynab_cleared_status(ynab_cleared: TransactionClearedStatus | None, expected: str):
    transaction = TransactionWithYnabDataFactory()
    transaction.ynab_cleared = ynab_cleared

    assert transaction.ynab_cleared_status == expected


@pytest.mark.parametrize(
    ("status", "ynab_cleared", "expected"),
    [
        pytest.param(MatchStatus.UNMATCHED, None, "", id="an unmatched transaction shows nothing"),
        pytest.param(MatchStatus.MATCHED, UNCLEARED, "🔗", id="a full match is always a link"),
        pytest.param(
            MatchStatus.PARTIAL_MATCH, CLEARED, "🔗", id="a cleared partial match is a link"
        ),
        pytest.param(
            MatchStatus.PARTIAL_MATCH, RECONCILED, "🔗", id="a reconciled partial match is a link"
        ),
        pytest.param(
            MatchStatus.PARTIAL_MATCH,
            UNCLEARED,
            "🔍",
            id="an uncleared partial match asks to be reviewed",
        ),
    ],
)
def test_match_emoji(
    status: MatchStatus, ynab_cleared: TransactionClearedStatus | None, expected: str
):
    assert matched(ynab_cleared, status).match_emoji == expected


def test_match_emoji_rejects_a_partial_match_without_a_counterpart():
    transaction = TransactionWithYnabDataFactory()
    transaction.match_status = MatchStatus.PARTIAL_MATCH

    with pytest.raises(AssertionError, match="Cannot have a partial match"):
        _ = transaction.match_emoji


def test_reset_matching_unlinks_the_ynab_payee():
    transaction = TransactionWithYnabDataFactory(payee="MERCADONA SA 4412")
    transaction.match_status = MatchStatus.PARTIAL_MATCH
    transaction.partial_match = TransactionDetailFactory()
    transaction.ynab_payee = "Mercadona"
    transaction.ynab_payee_id = "payee-1"

    transaction.reset_matching()

    assert transaction.match_status is MatchStatus.UNMATCHED
    assert transaction.partial_match is None
    assert transaction.ynab_payee == "MERCADONA SA 4412"
    assert transaction.ynab_payee_id is None


@pytest.mark.xfail(
    reason=(
        "models.py:140-145 leaves cleared and ynab_id behind. A partial match against a "
        "reconciled YNAB transaction sets cleared to RECONCILED, so when the user rejects that "
        "match the transaction is still created in YNAB as reconciled and locked"
    ),
    strict=True,
)
def test_reset_matching_restores_the_imported_cleared_status():
    transaction = TransactionWithYnabDataFactory()
    transaction.match_status = MatchStatus.PARTIAL_MATCH
    transaction.partial_match = TransactionDetailFactory(cleared=RECONCILED)
    transaction.update_cleared_from_ynab(transaction.partial_match, reconcile=False)
    transaction.ynab_id = "ynab-1"

    transaction.reset_matching()

    assert transaction.cleared is CLEARED
    assert transaction.ynab_id is None


@pytest.mark.parametrize(
    ("ynab_cleared", "reconcile", "expected"),
    [
        pytest.param(RECONCILED, False, RECONCILED, id="a reconciled counterpart reconciles us"),
        pytest.param(
            RECONCILED, True, RECONCILED, id="reconciling a reconciled one changes nothing"
        ),
        pytest.param(CLEARED, True, RECONCILED, id="the reconcile flag reconciles a cleared one"),
        pytest.param(
            UNCLEARED, True, RECONCILED, id="the reconcile flag reconciles an uncleared one"
        ),
        pytest.param(UNCLEARED, False, CLEARED, id="an uncleared counterpart is only cleared"),
        pytest.param(CLEARED, False, CLEARED, id="a cleared counterpart leaves us cleared"),
    ],
)
def test_update_cleared_from_ynab(
    ynab_cleared: TransactionClearedStatus,
    reconcile: bool,
    expected: TransactionClearedStatus,
):
    transaction = TransactionWithYnabDataFactory()

    transaction.update_cleared_from_ynab(TransactionDetailFactory(cleared=ynab_cleared), reconcile)

    assert transaction.cleared is expected
