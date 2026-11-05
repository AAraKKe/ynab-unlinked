import pytest
from pytest_mock import MockerFixture

from tests.helpers.types import CliRunner

pytestmark = pytest.mark.version("missing")


def test_app_explains_how_to_install_the_web_extra(yul: CliRunner, mocker: MockerFixture):
    mocker.patch("ynab_unlinked.web.available", return_value=False)
    run = mocker.patch("ynab_unlinked.web.app.run")

    result = yul("app")

    assert result.exit_code == 1
    assert "uv tool install 'ynab-unlinked[web]'" in result.output
    assert "pip install 'ynab-unlinked[web]'" in result.output
    run.assert_not_called()


@pytest.mark.parametrize(
    ("args", "port", "open_browser"),
    [("app", None, True), ("app --port 8765 --no-browser", 8765, False)],
    ids=["defaults", "port-no-browser"],
)
def test_app_starts_the_web_app(
    yul: CliRunner, mocker: MockerFixture, args: str, port: int | None, open_browser: bool
):
    run = mocker.patch("ynab_unlinked.web.app.run")

    result = yul(args)

    assert result.exit_code == 0, result.output
    assert run.call_args.kwargs["port"] == port
    assert run.call_args.kwargs["open_browser"] is open_browser
