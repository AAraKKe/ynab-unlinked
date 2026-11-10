from pytest_mock import MockerFixture

from ynab_unlinked.cli import utils
from ynab_unlinked.text import YNAB_TOKEN_URL


def test_the_token_prompt_says_where_ynab_creates_one(mocker: MockerFixture):
    said = mocker.patch.object(utils, "info")
    asked = mocker.patch.object(utils, "question", return_value="a-token")

    assert utils.prompt_for_api_key() == "a-token"

    said.assert_called_once()
    assert YNAB_TOKEN_URL in said.call_args.args[0]
    assert asked.call_args.kwargs == {"password": True}
