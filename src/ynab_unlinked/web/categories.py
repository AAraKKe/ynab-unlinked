"""The budget's categories as the category pickers list them: by group, filtered as you type.

Shared by Settings › Categories (the "not spending" ones) and Settings › Net worth (the goal).
Plain Python over `store.StoredCategory`, tested directly.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from ynab_unlinked.store import StoredCategory

BALANCE_GOALS = ("TB", "TBD")
"""YNAB targets that are a balance to reach (by a date or not), the ones the plan can follow."""


@dataclass(frozen=True)
class Group:
    name: str
    categories: tuple[StoredCategory, ...]


def grouped(categories: Iterable[StoredCategory]) -> list[Group]:
    """The user's categories (YNAB's own left out) under their group, in YNAB's order."""
    groups: dict[str, list[StoredCategory]] = {}
    names: dict[str, str] = {}
    for category in categories:
        if category.internal:
            continue
        groups.setdefault(category.group_id, []).append(category)
        names[category.group_id] = category.group_name
    return [Group(names[key], tuple(items)) for key, items in groups.items()]


def _folded(text: str) -> str:
    """Lower case without accents or emoji, so `eat` finds `🍕 Eating out` and `cafe` `Café`."""
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return "".join(c for c in decomposed if c.isalnum() or c.isspace()).strip()


def matching(groups: Sequence[Group], text: str) -> list[Group]:
    """The categories whose name has every word of `text`; a group matching keeps them all."""
    words = _folded(text).split()
    if not words:
        return list(groups)
    found: list[Group] = []
    for group in groups:
        if all(word in _folded(group.name) for word in words):
            found.append(group)
            continue
        hits = tuple(c for c in group.categories if all(w in _folded(c.name) for w in words))
        if hits:
            found.append(Group(group.name, hits))
    return found


def balance_goals(categories: Iterable[StoredCategory]) -> list[StoredCategory]:
    """The categories with a balance target in YNAB, largest target first."""
    goals = [
        c for c in categories if not c.internal and c.goal_type in BALANCE_GOALS and c.goal_target
    ]
    return sorted(goals, key=lambda c: -(c.goal_target or 0))


def goal_category(
    categories: Sequence[StoredCategory], chosen: str | None
) -> StoredCategory | None:
    """The goal the plan follows: the chosen category while it still has a balance target,
    else the largest balance target. None when no category has one."""
    goals = balance_goals(categories)
    return next((c for c in goals if c.id == chosen), goals[0] if goals else None)
