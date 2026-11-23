import datetime as dt

import pytest

from tests.web.views.test_networth_flows import FORMATTER
from ynab_unlinked.core.finance import AccountMove, Breakdown, Flows, Group, Rules
from ynab_unlinked.store import Line
from ynab_unlinked.web.views.networth import flows, terms

CHECKING, SAVINGS, FUND, ELSEWHERE = "checking", "savings", "fund", "elsewhere"
RULES = Rules(
    on_budget={CHECKING: True, SAVINGS: True, FUND: False},
    not_spending=frozenset({"broker"}),
    returns=frozenset({SAVINGS, FUND}),
)


def line(amount: int, account: str = CHECKING, **given: str | None) -> Line:
    fields: dict[str, str | None] = {
        "payee_name": "Someone",
        "category_id": "groceries",
        "category_name": "Groceries",
        "transfer_account_id": None,
    } | given
    return Line("t", account, dt.date(2026, 5, 1), amount, **fields)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("said", "given", "kind"),
    [
        ("Income: salary", line(3_000_000, payee_name="Employer"), "income"),
        ("Income: a refund or a reimbursement", line(240_000, payee_name="Work"), "income"),
        ("Income: whatever its category", line(50_000, category_id="broker"), "income"),
        (
            "Income, not: moving money between your own accounts",
            line(500_000, transfer_account_id=SAVINGS),
            "transfers",
        ),
        (
            "Income, not: interest recorded as an adjustment of an account whose return is shown",
            line(12_000, SAVINGS, payee_name="Reconciliation Balance Adjustment"),
            "assets",
        ),
        ("Income, not: market gains", line(90_000, FUND, category_id=None), "assets"),
        ("Spending: a card payment to a shop", line(-40_000), "spending"),
        (
            "Spending, not: moving money to savings",
            line(-500_000, transfer_account_id=SAVINGS),
            "transfers",
        ),
        (
            "Spending, not: moving money out of what is counted",
            line(-500_000, transfer_account_id=ELSEWHERE),
            "outside",
        ),
        (
            "Spending, not: a category marked not spending, shown as Other",
            line(-500_000, category_id="broker"),
            "set_aside",
        ),
        (
            "Spending, not: a fall in what an investment is worth",
            line(-90_000, FUND, category_id=None),
            "assets",
        ),
    ],
    ids=lambda value: value if isinstance(value, str) else "",
)
def test_what_the_i_says_counts_is_what_the_numbers_count(said: str, given: Line, kind: str):
    assert RULES.kind(given) == kind


def test_other_holds_what_is_set_aside():
    assert Flows(set_aside=-5).other == -5
    assert flows.bridge(Flows(set_aside=-5))[0].label == "Other"


def test_the_reimbursed_ticket_raises_income_and_spending_and_saves_nothing():
    told, lines, _ = terms.refund_example(FORMATTER)

    assert "240.00€" in told
    spending, income, saved = (line.amount for line in lines)
    assert (spending, income) == (-terms.TICKET, terms.TICKET)
    assert saved == Flows(income=income, spending=spending).saved == 0


def test_the_growth_story_shows_money_put_in_is_not_growth():
    story = terms.growth_story(FORMATTER)
    rise, deposit, fall, recover = story.phases

    # Prices rise with nothing put in; the deposit raises both lines by the same amount
    assert story.put_in[rise.upto] == story.put_in[0]
    assert story.growth[rise.upto] > 0
    assert deposit.deposit
    assert story.put_in[deposit.upto] - story.put_in[rise.upto] == story.deposit
    assert story.worth[deposit.upto] - story.worth[rise.upto] == story.deposit
    assert set(story.growth[rise.upto : deposit.upto + 1]) == {story.growth[rise.upto]}
    assert min(story.growth[deposit.upto : fall.upto + 1]) < 0
    assert story.growth[recover.upto] > 0


def test_the_growth_story_is_slow_enough_to_read_and_its_deposit_does_not_dwarf_prices():
    story = terms.growth_story(FORMATTER)

    assert all(phase.lasts >= 3_500 for phase in story.phases)
    # The deposit rises over about a second and then holds, so it is not a passing spike
    deposit = next(phase for phase in story.phases if phase.deposit)
    assert deposit.ms >= 900 and deposit.hold_ms >= 2_000
    assert 16_000 <= story.loop_ms - story.pause_ms <= 20_000
    moves = [
        abs(story.growth[phase.upto] - story.growth[start.upto])
        for start, phase in zip(story.phases, story.phases[1:], strict=False)
        if not phase.deposit
    ] + [story.growth[story.phases[0].upto]]
    assert story.deposit <= 2 * min(move for move in moves if move)


def test_a_growth_row_says_its_return_and_an_income_row_where_it_arrived():
    names = {CHECKING: "Checking", SAVINGS: "Savings", FUND: "Fund"}
    income = Group("Employer", "Employer", 3_240_000, 2, (CHECKING, SAVINGS))
    growth = Group(FUND, FUND, -400_000, 1, (FUND,))
    moves = {
        FUND: AccountMove(FUND, 10_000_000, 10_600_000, Flows(assets=-400_000), -0.036, 30),
        SAVINGS: AccountMove(SAVINGS, 0, 10, Flows(income=10), None),
    }

    assert flows.row_subtitle("income", income, names, moves, 30) == "into Checking and Savings"
    assert flows.row_subtitle("assets", growth, names, moves, 30) == "−3.6% return"
    assert (
        flows.row_subtitle("assets", Group(SAVINGS, SAVINGS, 10, 1, ()), names, moves, 30) is None
    )
    assert flows.row_name("assets", growth, names) == "Fund"


def test_growth_rows_share_their_bar_either_way():
    up, down = Group("a", "a", 300, 2, ()), Group("b", "b", -100, 1, ())
    breakdown = Breakdown("assets", (up, down), ())

    assert flows.share(up, breakdown) == 0.75
    assert flows.row_caption("assets", down, breakdown) == "25% · 1 value change"
    assert flows.row_caption("spending", up, breakdown) == "75% · 2 transactions"
    tiny = Breakdown("income", (Group("a", "a", 999, 1, ()), Group("b", "b", 1, 1, ())), ())
    assert flows.row_caption("income", tiny.groups[1], tiny) == "<1% · 1 transaction"


@pytest.mark.parametrize(
    ("shown", "total", "expected"),
    [(12, 31, 19), (12, 200, flows.MORE), (31, 31, 0)],
    ids=["the rest", "the next batch", "all shown"],
)
def test_show_more_adds_the_next_batch(shown: int, total: int, expected: int):
    assert flows.more_count(shown, total) == expected
