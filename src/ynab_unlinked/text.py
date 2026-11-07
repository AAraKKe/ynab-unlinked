"""Small wording helpers the CLI and the web app share. No UI library."""


def plural(count: int, word: str) -> str:
    """ "1 file", "3 files"."""
    return f"{count} {word}{'' if count == 1 else 's'}"
