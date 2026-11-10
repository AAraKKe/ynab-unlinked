"""Small wording helpers the CLI and the web app share. No UI library."""

YNAB_TOKEN_URL = "https://app.ynab.com/settings/developer"
"""Where a Personal Access Token is created: YNAB's Account Settings, Developer Settings."""


def plural(count: int, word: str) -> str:
    """ "1 file", "3 files"."""
    return f"{count} {word}{'' if count == 1 else 's'}"


def import_message(created: int, account_name: str, file: str, excluded: int) -> str:
    """The message of an `import` activity entry, saying how many rows were left out."""
    message = f"Imported {plural(created, 'transaction')} to {account_name} from {file}"
    return f"{message} · {excluded} left out" if excluded else message
