import datetime as dt

import pytest
from ynab import TransactionClearedStatus

from tests.factories import DEFAULT_DATE, TransactionFactory
from ynab_unlinked.models import assign_import_ids, cleared_str, milliunits

# YNAB caps `import_id` at 36 characters
MAX_IMPORT_ID_LENGTH = 36


@pytest.mark.parametrize(
    ("amount", "expected"),
    [
        pytest.param(10.0, 10000, id="a whole inflow"),
        pytest.param(-25.5, -25500, id="an outflow with one decimal"),
        pytest.param(-0.15, -150, id="a small outflow of cents"),
        pytest.param(2.01, 2010, id="an amount a float cannot represent exactly"),
    ],
)
def test_milliunits(amount: float, expected: int):
    assert milliunits(amount) == expected


def test_import_id_follows_the_ynab_direct_import_convention():
    # YNAB rejects a second import of the same id, so the format has to be the one Direct Import
    # and File Based Import use, or the same row would be created twice
    [pending] = assign_import_ids([TransactionFactory(date=dt.date(2015, 12, 30), amount=-294.23)])

    assert pending.import_id == "YNAB:-294230:2015-12-30:1"


@pytest.mark.parametrize(
    "amount",
    [
        pytest.param(-1234567.89, id="a large outflow"),
        pytest.param(9999999.99, id="a large inflow"),
    ],
)
def test_import_id_fits_the_ynab_length_limit(amount: float):
    [pending] = assign_import_ids([TransactionFactory(amount=amount)])

    assert len(pending.import_id) <= MAX_IMPORT_ID_LENGTH


def test_identical_rows_are_numbered_by_their_occurrence():
    transactions = [TransactionFactory(amount=-1.5) for _ in range(3)]

    pending = assign_import_ids(transactions)

    assert [p.import_id for p in pending] == [
        "YNAB:-1500:2025-05-15:1",
        "YNAB:-1500:2025-05-15:2",
        "YNAB:-1500:2025-05-15:3",
    ]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        pytest.param("date", dt.date(2025, 5, 16), id="a different date starts its own count"),
        pytest.param("amount", -11.0, id="a different amount starts its own count"),
    ],
)
def test_the_occurrence_restarts_for_a_different_date_or_amount(field: str, value: object):
    first = TransactionFactory()
    second = TransactionFactory(**{field: value})

    pending = assign_import_ids([first, second])

    assert [p.import_id.rsplit(":", 1)[1] for p in pending] == ["1", "1"]


def test_the_occurrence_ignores_the_payee():
    # YNAB counts occurrences by date and amount alone. Keying on the payee too would hand the
    # second row a `:1` id that collides with the first one.
    pending = assign_import_ids(
        [TransactionFactory(payee="Mercadona"), TransactionFactory(payee="Carrefour")]
    )

    assert [p.import_id.rsplit(":", 1)[1] for p in pending] == ["1", "2"]


def test_an_overlapping_export_reuses_the_ids_of_the_rows_it_repeats():
    # Two exports that share their first rows must produce the same ids for them, otherwise the
    # overlap is imported a second time instead of being rejected by YNAB.
    first_export = [
        TransactionFactory(date=DEFAULT_DATE - dt.timedelta(days=1)),
        TransactionFactory(),
    ]
    second_export = first_export + [TransactionFactory(payee="Bakery", amount=-3.0)]

    assert [p.import_id for p in assign_import_ids(first_export)] == [
        p.import_id for p in assign_import_ids(second_export)[:2]
    ]


def test_the_legacy_import_id_is_the_digest_previous_releases_uploaded():
    # Transactions imported before the YNAB convention carry this id in YNAB. If the digest ever
    # changes, every one of them is imported again as a duplicate.
    [pending] = assign_import_ids([TransactionFactory(amount=-10.5)])

    assert pending.legacy_import_id == "14110f975124ca05a3a2feeb647145"


def test_the_legacy_import_id_of_a_repeated_row_keeps_its_own_counter():
    pending = assign_import_ids([TransactionFactory(amount=-10.5) for _ in range(2)])

    assert len({p.legacy_import_id for p in pending}) == 2


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        pytest.param(TransactionClearedStatus.RECONCILED, "🔒 Reconciled", id="reconciled"),
        pytest.param(TransactionClearedStatus.CLEARED, "✅ Cleared", id="cleared"),
        pytest.param(TransactionClearedStatus.UNCLEARED, "Uncleared", id="uncleared"),
    ],
)
def test_cleared_str(status: TransactionClearedStatus, expected: str):
    assert cleared_str(status) == expected
