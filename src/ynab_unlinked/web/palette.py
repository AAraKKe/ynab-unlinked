"""The commands of the command palette and how a typed query finds them. No NiceGUI here.

A command goes somewhere (`path`) or does something (`action`, a name the shell knows:
`sync`, `theme`, `sidebar`). Pages and their tabs are registered by the views
(`shell.command`); the budget's categories and accounts are read when the palette opens.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from urllib.parse import urlencode

from ynab_unlinked.config import LatestConfig
from ynab_unlinked.store import Store
from ynab_unlinked.web import accounts as tracking
from ynab_unlinked.web.paths import NETWORTH_PATH, SPENDING_PATH

LIMIT = 9
"""How many results a query shows: the list never scrolls."""

GO_TO = "Go to"
ACTIONS = "Actions"
CATEGORIES = "Categories"
ACCOUNTS = "Accounts"


@dataclass(frozen=True)
class Command:
    key: str
    """Unique; the result row is marked `palette-<key>`."""
    title: str
    section: str
    icon: str
    path: str | None = None
    action: str | None = None
    hint: str = ""
    """Muted text on the right: where it lives ("Settings") or what it belongs to (a group)."""
    keywords: str = ""
    """Other words that find it, never shown."""
    quiet: bool = False
    """Left out until something is typed: tabs, and the budget's categories and accounts."""


def fold(text: str) -> str:
    """Lower case without accents, so "cafe" finds "Café"."""
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def _score(command: Command, words: Sequence[str]) -> int | None:
    """How well `words` match, lower is better; None when one of them is nowhere."""
    title = fold(command.title)
    rest = fold(f"{command.hint} {command.keywords}")
    score = 0
    for word in words:
        if title.startswith(word):
            score += 0
        elif any(part.startswith(word) for part in title.replace("›", " ").split()):
            score += 1
        elif word in title:
            score += 2
        elif word in rest:
            score += 3
        else:
            return None
    return score


def search(commands: Iterable[Command], query: str, limit: int = LIMIT) -> list[Command]:
    """The `limit` commands a query finds best; without a query, all that are not quiet.

    Every word typed has to be in the title, the hint or the keywords. Among equals the
    order of `commands` is kept, so pages come before categories.
    """
    words = fold(query).split()
    if not words:
        return [command for command in commands if not command.quiet]
    scored = [
        (score, index, command)
        for index, command in enumerate(commands)
        if (score := _score(command, words)) is not None
    ]
    return [command for _, _, command in sorted(scored, key=lambda item: item[:2])][:limit]


def budget_commands(store: Store, config: LatestConfig) -> list[Command]:
    """A command per category (its months in Spending) and per counted account (its history
    in Net worth). Blocking: run it through `run.io_bound`."""
    budget_id = config.budget.id
    commands = [
        Command(
            key=f"category-{category.id}",
            title=category.name,
            section=CATEGORIES,
            icon="spending",
            path=f"{SPENDING_PATH}?{urlencode({'category': category.id})}",
            hint=category.group_name,
            quiet=True,
        )
        for category in store.categories(budget_id)
        if not category.hidden and not category.internal
    ]
    commands += [
        Command(
            key=f"account-{account.id}",
            title=account.name,
            section=ACCOUNTS,
            icon="networth",
            path=f"{NETWORTH_PATH}?{urlencode({'account': account.id})}",
            hint="Account",
            quiet=True,
        )
        for account in tracking.effective_accounts(config, store.accounts(budget_id))
    ]
    return commands
