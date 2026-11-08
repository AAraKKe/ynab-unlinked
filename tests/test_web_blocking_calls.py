"""The views keep blocking writes off the event loop by construction.

Every config save in a view goes through `shell.save_config`, which runs it through
`run.io_bound` (`tests/web/test_shell.py` checks that), and every activity entry is written
by handing `store.log` to `run.io_bound`. A direct call here would freeze every open page.
"""

import re
from pathlib import Path

VIEWS = Path(__file__).parent.parent / "src" / "ynab_unlinked" / "web" / "views"
# A config saved by hand; `self.save()` is a view's own helper around `shell.save_config`
DIRECT_SAVE = re.compile(r"\b(update_config|edit_config)\(|(?<!self)\.save\(\)")


def blocks_the_loop(line: str) -> bool:
    return bool(DIRECT_SAVE.search(line)) or ("store.log(" in line and "io_bound" not in line)


def test_views_never_save_the_config_or_log_on_the_event_loop():
    offending = [
        f"{path.relative_to(VIEWS)}:{number}: {line.strip()}"
        for path in sorted(VIEWS.rglob("*.py"))
        for number, line in enumerate(path.read_text().splitlines(), start=1)
        if blocks_the_loop(line)
    ]

    assert offending == []
