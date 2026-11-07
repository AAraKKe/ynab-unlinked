from pathlib import Path

import ynab_unlinked

PACKAGE = Path(ynab_unlinked.__file__).parent


def test_package_ships_no_test_modules():
    # Everything under src/ynab_unlinked ends up in the wheel; a stray scratch script there
    # would run against the user's real config on import.
    strays = sorted(
        str(path.relative_to(PACKAGE))
        for path in PACKAGE.rglob("test*.py")
        if "__pycache__" not in path.parts
    )
    assert strays == []
