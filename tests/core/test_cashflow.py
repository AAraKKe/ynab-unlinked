import datetime as dt
from pathlib import Path

import pytest

from tests.factories import StoredAccountFactory, StoredTransactionFactory
from tests.helpers.store import upsert
from ynab_unlinked.core.cashflow import Categories, cash_flow, volatility
from ynab_unlinked.core.finance import Rules
from ynab_unlinked.store import Store

BUDGET = "budget"
CHECKING = "checking"
RULES = Rules(on_budget={CHECKING: True})


@pytest.mark.parametrize(
    ("spent", "label"),
    [
        ([950] * 12, "steady"),
        ([300, 280, 320, 310, 290, 300, 330, 270, 300, 310, 290, 300], "steady"),
        ([500, 250, 800, 400, 700, 300, 600, 350, 750, 300, 450, 650], "variable"),
        ([0, 0, 2000, 0, 50, 0, 0, 1600, 0, 0, 100, 0], "spiky"),
        ([0, 0, 120, 0, 0, 0, 0, 0, 120, 0, 0, 0], "lumpy"),
        ([0, 0, 0, 0, 0, 0, 0, 0, 5000, 0, 0, 0], None),
        ([300, 300, 300], None),
    ],
    ids=[
        "rent",
        "groceries",
        "eating out",
        "holidays",
        "a charge twice a year",
        "a single purchase",
        "too few months",
    ],
)
def test_volatility_labels(spent: list[int], label: str | None):
    assert volatility(spent).label == label


@pytest.fixture
def store(tmp_path: Path) -> Store:
    return Store(tmp_path / "store.sqlite")


def seed(store: Store, rows: list[tuple[str, int, str, str | None]]) -> None:
    upsert(
        store,
        BUDGET,
        accounts=[StoredAccountFactory(id=CHECKING)],
        transactions=[
            StoredTransactionFactory(
                id=f"t{n}",
                account_id=CHECKING,
                date=dt.date.fromisoformat(day),
                amount=amount,
                payee_name=payee,
                category_id=category,
            )
            for n, (day, amount, payee, category) in enumerate(rows)
        ],
    )


def test_months_add_up_income_and_spending_and_the_running_month_is_not_complete(store: Store):
    seed(
        store,
        [
            ("2026-09-01", 3_000_000, "Employer", "rta"),
            ("2026-09-03", -1_000_000, "Landlord", "rent"),
            ("2026-09-10", 50_000, "Shop", "groceries"),
            ("2026-10-01", 3_000_000, "Employer", "rta"),
            ("2026-10-03", -1_000_000, "Landlord", "rent"),
            ("2026-11-01", 3_000_000, "Employer", "rta"),
        ],
    )

    flow = cash_flow(store, BUDGET, RULES, dt.date(2026, 9, 1), dt.date(2026, 11, 9))

    assert [(m.income, m.spending, m.complete) for m in flow.months] == [
        (3_050_000, 1_000_000, True),
        (3_000_000, 1_000_000, True),
        (3_000_000, 0, False),
    ]
    # The running month is in the chart but not in the averages
    assert flow.mean_income == 3_025_000
    assert flow.savings_rate == pytest.approx(4_050_000 / 6_050_000)
    assert [m.name for m in flow.income] == ["Employer", "Shop"]


def test_a_month_far_above_the_usual_is_labelled_by_what_stood_out_or_by_its_note(store: Store):
    rows: list[tuple[str, int, str, str | None]] = []
    for month in range(1, 7):
        rows += [
            (f"2026-{month:02d}-01", 3_000_000, "Employer", "rta"),
            (f"2026-{month:02d}-05", -1_000_000, "Landlord", "rent"),
        ]
    rows += [
        ("2026-03-15", 2_000_000, "Stock sale", "rta"),
        ("2026-05-20", -2_500_000, "Airline", "trip"),
    ]
    seed(store, rows)
    notes = {dt.date(2026, 6, 1): "Moved flat\nand more"}

    flow = cash_flow(
        store,
        BUDGET,
        RULES,
        dt.date(2026, 1, 1),
        dt.date(2026, 6, 30),
        categories=Categories(names={"trip": "🏝 Vacation"}),
        notes=notes,
    )

    assert [m.label for m in flow.months] == [
        None,
        None,
        "Stock sale",
        None,
        "🏝 Vacation",
        "Moved flat",
    ]


def test_core_spending_leaves_out_one_offs(store: Store):
    rows: list[tuple[str, int, str, str | None]] = []
    for month in range(1, 7):
        rows.append((f"2026-{month:02d}-05", -1_000_000, "Landlord", "rent"))
    rows.append(("2026-03-20", -2_400_000, "Airline", "trip"))
    rows.append(("2026-05-20", -600_000, "Airline", "trip"))
    seed(store, rows)

    flow = cash_flow(
        store,
        BUDGET,
        RULES,
        dt.date(2026, 1, 1),
        dt.date(2026, 6, 30),
        categories=Categories(groups={"rent": "Bills", "trip": "Fun"}),
    )

    assert [t.volatility.label for t in flow.categories] == ["steady", "spiky"]
    assert flow.core_spending() == pytest.approx(1_000_000)
    assert [(g.name, round(g.share, 2)) for g in flow.groups()] == [("Bills", 0.67), ("Fun", 0.33)]
