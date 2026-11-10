"""Check that every changelog fragment is named after the PR that made it.

    uv run poe tc-names

A fragment is `changelog/<PR number>.<type>.md`, so the release notes link each entry to its
PR. `+<slug>.<type>.md` builds an entry without a number: it is only for the commits before
the PR exists, and is renamed once the PR has its number.
"""

from __future__ import annotations

import sys
from pathlib import Path

CHANGELOG = Path(__file__).resolve().parent.parent / "changelog"


def unnumbered(directory: Path = CHANGELOG) -> list[Path]:
    """The fragments that name no PR, by name."""
    return sorted(directory.glob("+*.md"))


def main(directory: Path = CHANGELOG) -> int:
    orphans = unnumbered(directory)
    if not orphans:
        return 0
    print("Changelog fragments must be named after their PR, so the release notes link to it.")
    print("Open the PR, then rename (git mv) and push:")
    for path in orphans:
        kind = path.name.split(".")[-2] if path.name.count(".") >= 2 else "<type>"
        print(f"  changelog/{path.name} -> changelog/<PR number>.{kind}.md")
    return 1


if __name__ == "__main__":
    sys.exit(main())
