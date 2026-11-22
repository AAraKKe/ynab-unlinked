"""Small wording helpers the CLI and the web app share. No UI library."""

from collections.abc import Sequence

YNAB_TOKEN_URL = "https://app.ynab.com/settings/developer"
"""Where a Personal Access Token is created: YNAB's Account Settings, Developer Settings."""


def plural(count: int, word: str) -> str:
    """ "1 file", "3 files"."""
    return f"{count} {word}{'' if count == 1 else 's'}"


def name_list(names: Sequence[str]) -> str:
    """ "a.txt", "a.txt and b.pdf", "a.txt, b.pdf and c.xlsx"."""
    if len(names) < 2:
        return "".join(names)
    return f"{', '.join(names[:-1])} and {names[-1]}"


def import_message(
    created: int, account_name: str, file: str, excluded: int, refused: int = 0
) -> str:
    """The message of an `import` activity entry, saying how many rows YNAB did not take
    and how many were left out."""
    message = f"Imported {plural(created, 'transaction')} to {account_name} from {file}"
    if refused:
        message += f" · YNAB did not take {refused}"
    if excluded:
        message += f" · {excluded} left out"
    return message


def refused_why(count: int) -> str:
    """Why YNAB did not take rows yul sent, for the import screens of both frontends."""
    one = count == 1
    return (
        f"YNAB answered that {'it was' if one else 'they were'} imported before. That happens "
        f"when a transaction was imported and then deleted in YNAB: YNAB will not take "
        f"{'it' if one else 'them'} again, now or on any later import."
    )
