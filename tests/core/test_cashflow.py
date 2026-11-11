import datetime as dt
from pathlib import Path

import pytest

from tests.factories import StoredAccountFactory, StoredTransactionFactory
from tests.helpers.store import upsert
from ynab_unlinked.core.cashflow import Categories, cash_flow, rhythm, volatility
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
        ([30, 40, 25, 35, 30, 300, 30, 45, 20, 35, 30, 400], "spiky"),
        ([50, 0, 50, 0, 48, 0, 50, 50, 0, 48, 0, 50], "spiky"),
        ([0, 0, 2000, 0, 50, 0, 0, 1600, 0, 0, 100, 0], "lumpy"),
        ([0, 0, 120, 0, 0, 0, 0, 0, 120, 0, 0, 0], "lumpy"),
        ([300, 0, 0, 310, 0, 0, 290, 0, 0, 300, 0, 0, 305], "lumpy"),
        # Three charges alike and one small purchase: what the charges cost does not matter
        ([41, *[0] * 6, 11, *[0] * 4, 41, *[0] * 11, 41], "lumpy"),
        # It spends in eleven months of thirteen, but nine of them are next to nothing
        ([600, 5, 0, 6, 5, 0, 5, 7, 5, 6, 5, 6, 600], "lumpy"),
        ([0, 0, 0, 0, 0, 0, 0, 0, 5000, 0, 0, 0], None),
        ([300, 300, 300], None),
    ],
    ids=[
        "rent",
        "groceries",
        "eating out",
        "gifts",
        "a haircut every other month",
        "holidays",
        "a charge twice a year",
        "a charge every three months",
        "a yearly charge and a stray purchase",
        "small fees and a yearly charge",
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


def test_months_before_a_category_existed_are_not_counted_as_quiet(store: Store):
    # Rent starts in month 4 of a year and is the same every month from then on
    rows = [(f"2026-{month:02d}-05", -1_000_000, "Landlord", "rent") for month in range(4, 13)]
    seed(store, rows)

    flow = cash_flow(store, BUDGET, RULES, dt.date(2026, 1, 1), dt.date(2026, 12, 31))

    assert flow.categories[0].volatility.label == "steady"
    assert flow.categories[0].spent[:3] == (0, 0, 0)


# ---- what a category is comes from its history, not from the range -----------------------------


def history_rows(first_year: int, last: dt.date) -> list[tuple[str, int, str, str | None]]:
    """Rent every month and an insurance every January, from `first_year` to `last`."""
    rows: list[tuple[str, int, str, str | None]] = []
    month = dt.date(first_year, 1, 1)
    while month <= last:
        rows.append((month.replace(day=3).isoformat(), -1_000_000, "Landlord", "rent"))
        if month.month == 1:
            rows.append((month.replace(day=9).isoformat(), -480_000, "Insurer", "insurance"))
        month = dt.date(month.year + month.month // 12, month.month % 12 + 1, 1)
    return rows


def labels(store: Store, start: str, end: str) -> dict[str, str | None]:
    flow = cash_flow(store, BUDGET, RULES, dt.date.fromisoformat(start), dt.date.fromisoformat(end))
    return {trend.category_id or "": trend.volatility.label for trend in flow.categories}


def test_a_yearly_charge_is_lumpy_in_a_range_that_holds_one_of_them(store: Store):
    seed(store, history_rows(2023, dt.date(2026, 3, 31)))

    # Three months, one insurance in them: three years of history say what it is
    assert labels(store, "2026-01-01", "2026-03-31") == {"rent": "steady", "insurance": "lumpy"}


def test_the_range_does_not_change_what_a_category_is(store: Store):
    seed(store, history_rows(2023, dt.date(2026, 3, 31)))

    short = labels(store, "2026-01-01", "2026-03-31")
    year = labels(store, "2025-04-01", "2026-03-31")
    everything = labels(store, "2023-01-01", "2026-03-31")

    assert short == year == everything == {"rent": "steady", "insurance": "lumpy"}


def test_a_range_longer_than_the_history_is_measured_whole(store: Store):
    # A charge every other January: two of them in five years, none in the last three but one
    rows = history_rows(2021, dt.date(2026, 3, 31))
    rows = [row for row in rows if row[3] != "insurance"]
    rows += [
        ("2021-01-09", -480_000, "Insurer", "insurance"),
        ("2023-01-09", -480_000, "Insurer", "insurance"),
    ]
    seed(store, rows)

    assert labels(store, "2021-01-01", "2026-03-31")["insurance"] == "lumpy"


def test_a_young_budget_has_too_little_history_for_a_label(store: Store):
    seed(store, history_rows(2026, dt.date(2026, 4, 30)))

    assert labels(store, "2026-01-01", "2026-04-30") == {"rent": None, "insurance": None}


def test_the_months_before_the_budget_began_are_not_history(store: Store):
    # Eight months of rent: steady, not a category that was quiet for two years before. One
    # insurance is a single purchase so far
    seed(store, [row for row in history_rows(2025, dt.date(2026, 3, 31)) if row[0] >= "2025-08"])

    assert labels(store, "2026-01-01", "2026-03-31") == {"rent": "steady", "insurance": None}


def test_a_range_that_is_only_the_running_month_shows_it_so_far(store: Store):
    seed(store, history_rows(2023, dt.date(2026, 4, 10)))

    flow = cash_flow(store, BUDGET, RULES, dt.date(2026, 4, 1), dt.date(2026, 4, 10))

    assert flow.running_only
    assert [(m.month, m.complete) for m in flow.measured] == [(dt.date(2026, 4, 1), False)]
    assert flow.mean_spending == 1_000_000
    [rent] = flow.categories
    assert (rent.spent, rent.volatility.label) == ((1_000_000,), "steady")
    # Averages of income and the savings rate still wait for a complete month
    assert (flow.mean_income, flow.savings_rate) == (0, None)


def test_with_a_complete_month_the_running_one_is_left_out_of_the_averages(store: Store):
    seed(store, history_rows(2023, dt.date(2026, 4, 10)))

    flow = cash_flow(store, BUDGET, RULES, dt.date(2026, 3, 1), dt.date(2026, 4, 10))

    assert not flow.running_only
    assert [m.month for m in flow.measured] == [dt.date(2026, 3, 1)]
    assert flow.categories[0].spent == (1_000_000,)


# ---- the charges of a category that spends every so often -------------------------------------


@pytest.mark.parametrize(
    ("spent", "charge", "charges", "every", "set_aside", "alike"),
    [
        # A yearly subscription: its price over twelve months
        ([171_000, *[0] * 11, 171_000, *[0] * 5], 171_000, 2, 12, 14_250, True),
        # An insurance twice a year, a little dearer each time
        (
            [480_000, 0, 0, 0, 0, 0, 500_000, 0, 0, 0, 0, 0, 520_000],
            500_000,
            3,
            6,
            500_000 / 6,
            True,
        ),
        # Two purchases that have nothing to do with each other
        ([120_000, 0, 0, 0, 6_750_000], 3_435_000, 2, 4, 858_750, False),
        # One charge so far: nothing to tell how often it comes
        ([0, 0, 171_000, 0], 171_000, 1, None, None, True),
        ([0, 0, 0], 0, 0, None, None, False),
    ],
    ids=["yearly", "twice a year", "unlike purchases", "one charge", "nothing"],
)
def test_the_rhythm_of_a_category_is_its_charge_and_how_far_apart_charges_are(
    spent: list[int],
    charge: float,
    charges: int,
    every: float | None,
    set_aside: float | None,
    alike: bool,
):
    beat = rhythm(spent)

    assert (beat.charge, beat.charges, beat.every, beat.alike) == (charge, charges, every, alike)
    assert beat.set_aside == pytest.approx(set_aside)


def test_a_category_keeps_the_history_its_label_was_told_from(store: Store):
    seed(store, history_rows(2024, dt.date(2026, 3, 31)))

    flow = cash_flow(store, BUDGET, RULES, dt.date(2026, 1, 1), dt.date(2026, 3, 31))

    insurance = next(t for t in flow.categories if t.category_id == "insurance")
    # The range holds one charge; the history holds the three Januaries
    assert insurance.spent == (480_000, 0, 0)
    assert (flow.history[0], flow.history[-1]) == (dt.date(2024, 1, 1), dt.date(2026, 3, 1))
    assert [flow.history[i] for i, v in enumerate(insurance.past) if v] == [
        dt.date(2024, 1, 1),
        dt.date(2025, 1, 1),
        dt.date(2026, 1, 1),
    ]
    assert rhythm(insurance.past).set_aside == 40_000
