from pathlib import Path

import ynab_unlinked.web

WEB = Path(ynab_unlinked.web.__file__).parent


def test_scripts_find_their_element_through_nicegui():
    """NiceGUI 4 renamed the DOM id of an element from `c<id>` to `ng-<id>`, and the count up
    and the Growth animation, which built the id by hand, silently stopped. `getHtmlElement(id)`
    is NiceGUI's own lookup and follows it."""
    by_hand = [
        f"{path.relative_to(WEB)}:{number}"
        for path in sorted(WEB.rglob("*.py"))
        for number, line in enumerate(path.read_text().splitlines(), start=1)
        if "getElementById" in line
    ]

    assert by_hand == []
