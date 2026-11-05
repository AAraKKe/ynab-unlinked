from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from pytest_mock import MockerFixture

from ynab_unlinked.cli.display import CliProgress, bullet_list, process


@pytest.fixture
def printed(mocker: MockerFixture) -> MagicMock:
    return mocker.patch("ynab_unlinked.cli.display.console").return_value.print


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


@pytest.mark.parametrize(
    ("report", "expected_prints"),
    [
        pytest.param(lambda p: p.done("Transactions read"), ["✔ Transactions read"], id="done"),
        pytest.param(lambda p: p.done(), [], id="a-silent-done"),
        pytest.param(lambda p: p.info("3 files found"), ["3 files found"], id="info"),
        pytest.param(lambda p: p.warn("Skipped a row"), ["Skipped a row"], id="warn"),
    ],
)
def test_cli_progress_prints_each_report_on_the_terminal(
    printed: MagicMock, report, expected_prints: list[str]
):
    with CliProgress() as progress:
        report(progress)

    messages = [call.args[0] for call in printed.call_args_list]
    assert len(messages) == len(expected_prints)
    assert all(
        expected in message for expected, message in zip(expected_prints, messages, strict=True)
    )


def test_cli_progress_stops_the_spinner_when_the_step_raises(mocker: MockerFixture):
    status = mocker.patch("ynab_unlinked.cli.display.Status")

    with pytest.raises(RuntimeError), CliProgress() as progress:
        progress.start("Reading transactions...")
        raise RuntimeError("YNAB is down")

    status.return_value.__exit__.assert_called_once()
