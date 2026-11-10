import pytest

from ynab_unlinked.store import StoredCategory
from ynab_unlinked.web.categories import balance_goals, goal_category, grouped, matching


def category(
    id: str,
    name: str,
    group: str = "Everyday",
    *,
    internal: bool = False,
    goal_type: str | None = None,
    goal_target: int | None = None,
) -> StoredCategory:
    return StoredCategory(
        id=id,
        name=name,
        group_id=group.lower(),
        group_name=group,
        hidden=False,
        internal=internal,
        balance=0,
        goal_type=goal_type,
        goal_target=goal_target,
    )


CATEGORIES = [
    category("rta", "Inflow: Ready to Assign", "Internal Master Category", internal=True),
    category("eat", "🍕 Eating out"),
    category("cafe", "☕️ Café"),
    category("rent", "🏠 Rent", "Bills"),
    category("down", "🏠 Down Payment", "Goals", goal_type="TB", goal_target=70_000_000),
    category("trip", "🏝 Vacation", "Goals", goal_type="TBD", goal_target=3_000_000),
    category("food", "🛒 Groceries", goal_type="NEED", goal_target=280_000),
]


def names(groups) -> list[tuple[str, list[str]]]:
    return [(group.name, [c.name for c in group.categories]) for group in groups]


def test_categories_are_listed_under_their_group_without_ynabs_own():
    assert names(grouped(CATEGORIES)) == [
        ("Everyday", ["🍕 Eating out", "☕️ Café", "🛒 Groceries"]),
        ("Bills", ["🏠 Rent"]),
        ("Goals", ["🏠 Down Payment", "🏝 Vacation"]),
    ]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("eat", [("Everyday", ["🍕 Eating out"])]),
        ("CAFE", [("Everyday", ["☕️ Café"])]),
        ("down pay", [("Goals", ["🏠 Down Payment"])]),
        ("goals", [("Goals", ["🏠 Down Payment", "🏝 Vacation"])]),
        ("   ", None),
        ("nothing like it", []),
    ],
    ids=[
        "part of a name",
        "without case or accents",
        "every word",
        "a group keeps all its categories",
        "blank lists everything",
        "no match",
    ],
)
def test_typing_filters_the_categories(text: str, expected):
    groups = grouped(CATEGORIES)

    found = names(matching(groups, text))

    assert found == (names(groups) if expected is None else expected)


def test_balance_goals_are_the_balance_targets_largest_first():
    assert [c.id for c in balance_goals(CATEGORIES)] == ["down", "trip"]


@pytest.mark.parametrize(
    ("chosen", "expected"),
    [(None, "down"), ("trip", "trip"), ("food", "down"), ("gone", "down")],
    ids=["the largest by default", "the chosen one", "not a balance target", "deleted"],
)
def test_the_goal_is_the_chosen_balance_target_or_the_largest(chosen, expected):
    goal = goal_category(CATEGORIES, chosen)

    assert goal is not None and goal.id == expected


def test_no_goal_without_a_balance_target():
    assert goal_category([category("eat", "Eating out")], None) is None
