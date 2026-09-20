from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from pytest_mock import MockerFixture

from ynab_unlinked.display import bullet_list, process


@pytest.fixture
def printed(mocker: MockerFixture) -> MagicMock:
    return mocker.patch("ynab_unlinked.display.console").return_value.print


@pytest.mark.parametrize(
    "items, expected",
    [
        pytest.param([], "", id="nothing to list"),
        pytest.param(["only one"], " • only one", id="a single item"),
        pytest.param(["first", "second"], " • first\n • second", id="one line per item"),
        pytest.param(iter(["lazy"]), " • lazy", id="an iterator is consumed"),
    ],
)
def test_bullet_list(items, expected: str):
    assert bullet_list(items) == expected


@pytest.mark.parametrize(
    "completed_message, expected_prints",
    [
        pytest.param("Done!", 1, id="the completion message is shown when given"),
        pytest.param(None, 0, id="nothing is shown when the work is silent"),
    ],
)
def test_process_reports_completion_only_when_asked_to(
    printed: MagicMock, completed_message: str | None, expected_prints: int
):
    with process("Working...", completed_message):
        pass

    assert printed.call_count == expected_prints
