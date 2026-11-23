"""What the "i" of Net worth's waterfall says: what Income, Spending and Growth mean.

Each term's meaning and what it counts or not (true of `core.finance.Rules.kind`), a reimbursed
ticket that raises Income and Spending alike, and the made-up account of the Growth animation:
its worth and the money put in it, point by point, and the phases the animation plays. Plain
Python, tested directly; `terms_story` draws it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from ynab_unlinked.formatter import Formatter

TERMS_TITLE = "What Income, Spending and Growth mean"


@dataclass(frozen=True)
class Term:
    kind: str
    title: str
    meaning: str
    counts: tuple[str, ...]
    not_counted: tuple[str, ...]


TERM_MEANINGS = (
    Term(
        "income",
        "Income",
        "Money that arrived in your budget accounts from someone else, whatever its category.",
        ("Salary, benefits, a sale", "A refund or a reimbursement"),
        (
            "Moving money between your own accounts",
            "Market gains, and interest recorded as a balance adjustment of an account whose "
            "return Movers shows (Settings › Net worth): that is Growth",
        ),
    ),
    Term(
        "spending",
        "Spending",
        "Money that left your budget accounts to someone else.",
        ("Rent, groceries, a card payment to a shop",),
        (
            "Moving money to savings or investments",
            'Categories marked "not spending" in Settings: they show as Other',
            "A fall in what an investment is worth: that is Growth",
        ),
    ),
    Term(
        "assets",
        "Growth",
        "What your accounts gained or lost on their own: what they are worth, minus what you "
        "put in.",
        (),
        (),
    ),
)


@dataclass(frozen=True)
class ExampleLine:
    label: str
    amount: int


TICKET = 240_000


def refund_example(formatter: Formatter) -> tuple[str, list[ExampleLine], str]:
    """A ticket paid and reimbursed by work: it raises Income and Spending alike."""
    ticket = formatter.format_amount_milli(TICKET)
    return (
        f"You pay a {ticket} train ticket for work, and work pays it back.",
        [
            ExampleLine("Spending", -TICKET),
            ExampleLine("Income", TICKET),
            ExampleLine("What you saved", 0),
        ],
        "So Income and Spending both read higher than what you earned and what things cost you.",
    )


@dataclass(frozen=True)
class GrowthPhase:
    """One part of the Growth animation: it draws the points up to `upto` in `ms`, then
    holds still for `hold_ms`."""

    caption: str
    upto: int
    ms: int
    hold_ms: int = 0
    deposit: bool = False
    """The money put in: the chart says how much while it runs and holds."""

    @property
    def lasts(self) -> int:
        return self.ms + self.hold_ms


@dataclass(frozen=True)
class GrowthStory:
    """An account's worth and the money put in it, point by point, in milliunits."""

    worth: tuple[int, ...]
    put_in: tuple[int, ...]
    phases: tuple[GrowthPhase, ...]
    deposit: int
    pause_ms: int

    @property
    def growth(self) -> tuple[int, ...]:
        return tuple(w - p for w, p in zip(self.worth, self.put_in, strict=True))

    @property
    def loop_ms(self) -> int:
        return sum(phase.lasts for phase in self.phases) + self.pause_ms


STORY_START = 2_000_000
DEPOSIT = 500_000
DEPOSIT_STEPS = 4


def _path(start: int, end: int, steps: int, wiggle: int, seed: int) -> list[int]:
    """`steps` points from after `start` to `end`, eased, with a small deterministic wobble
    that is zero at both ends."""
    points: list[int] = []
    for i in range(1, steps + 1):
        t = i / steps
        eased = t * t * (3 - 2 * t)
        wobble = math.sin(t * math.pi * (3 + seed)) * math.sin(t * math.pi) * wiggle
        points.append(round((start + (end - start) * eased + wobble) / 1000) * 1000)
    points[-1] = end
    return points


def growth_story(formatter: Formatter) -> GrowthStory:
    """Prices rise, 500 more is put in, prices fall below what was put in, then recover.

    The deposit is its own unhurried phase (both lines rise together, then hold), and the
    scale keeps it from dwarfing the price moves: it is about the size of each of them.
    """
    money = formatter.format_amount_milli
    worth = [STORY_START]
    put_in = [STORY_START]
    rise = _path(STORY_START, 2_300_000, 24, 25_000, 0)
    worth += rise
    put_in += [STORY_START] * len(rise)
    risen = len(worth) - 1
    # The deposit: a few steps up, the same for both lines, so it reads as a slope, not a spike
    for step in range(1, DEPOSIT_STEPS + 1):
        worth.append(2_300_000 + DEPOSIT * step // DEPOSIT_STEPS)
        put_in.append(STORY_START + DEPOSIT * step // DEPOSIT_STEPS)
    deposited = len(worth) - 1
    fall = _path(2_800_000, 2_350_000, 24, 30_000, 1)
    worth += fall
    put_in += [STORY_START + DEPOSIT] * len(fall)
    fallen = len(worth) - 1
    recover = _path(2_350_000, 2_900_000, 26, 30_000, 2)
    worth += recover
    put_in += [STORY_START + DEPOSIT] * len(recover)
    phases = (
        GrowthPhase(
            "Prices rise. Nothing was bought or sold, yet Growth goes up.", risen, 4_000, 400
        ),
        GrowthPhase(
            f"You put {money(DEPOSIT)} more in. Both lines rise together: that is your money, "
            "not Growth, which does not move.",
            deposited,
            1_100,
            2_800,
            deposit=True,
        ),
        GrowthPhase(
            "Prices fall. What the account is worth drops below what you put in: Growth goes "
            "below zero.",
            fallen,
            4_000,
            400,
        ),
        GrowthPhase("Prices recover, and so does Growth.", len(worth) - 1, 4_000, 1_600),
    )
    return GrowthStory(tuple(worth), tuple(put_in), phases, DEPOSIT, 1_500)


def deposit_label(formatter: Formatter) -> str:
    return f"+{formatter.format_amount_milli(DEPOSIT)} you put in"
