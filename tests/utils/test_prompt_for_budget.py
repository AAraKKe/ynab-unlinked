from __future__ import annotations

from uuid import UUID

import pytest
from pytest_mock import MockerFixture
from ynab import PlanDetail, PlanSummary

from tests.factories import PlanDetailFactory, SdkCurrencyFormatFactory
from ynab_unlinked.utils import prompt_for_budget

FIRST_BUDGET_ID = UUID("00000000-0000-0000-0000-000000000001")
SECOND_BUDGET_ID = UUID("00000000-0000-0000-0000-000000000002")
# A budget whose separators are the other way around from the factory default
SPANISH_FORMAT = SdkCurrencyFormatFactory(decimal_separator=",", group_separator=".")


def plan_detail(**overrides) -> PlanDetail:
    fields = {
        "id": SECOND_BUDGET_ID,
        "name": "Second Budget",
        "currency_format": SPANISH_FORMAT,
    }
    return PlanDetailFactory(**(fields | overrides))


@pytest.fixture
def client(mocker: MockerFixture):
    client_class = mocker.patch("ynab_unlinked.utils.Client")
    client_class.return_value.budgets.return_value = [
        PlanSummary(id=FIRST_BUDGET_ID, name="First Budget"),
        PlanSummary(id=SECOND_BUDGET_ID, name="Second Budget"),
    ]
    client_class.return_value.budget.return_value = plan_detail()
    return client_class


@pytest.fixture
def answer(monkeypatch: pytest.MonkeyPatch):
    def _answer(number: str):
        monkeypatch.setattr("builtins.input", lambda: number)

    return _answer


@pytest.mark.parametrize(
    "typed_number, requested_budget_id",
    [
        pytest.param("1", FIRST_BUDGET_ID, id="first"),
        pytest.param("2", SECOND_BUDGET_ID, id="second"),
    ],
)
def test_budget_is_selected_by_the_number_shown_to_the_user(
    client, answer, typed_number: str, requested_budget_id: UUID
):
    answer(typed_number)

    prompt_for_budget(api_key="an-api-key")

    client.return_value.budget.assert_called_once_with(str(requested_budget_id))


def test_selected_budget_details_are_mapped_into_the_config_budget(client, answer):
    answer("2")

    budget = prompt_for_budget(api_key="an-api-key")

    assert budget.id == str(SECOND_BUDGET_ID)
    assert budget.name == "Second Budget"
    assert budget.date_format == "DD/MM/YYYY"
    # Pins the field by field mapping: a swap between separators or symbols would survive
    # any looser assertion.
    assert budget.currency_format.model_dump() == {
        "iso_code": "EUR",
        "decimal_digits": 2,
        "decimal_separator": ",",
        "symbol_first": False,
        "group_separator": ".",
        "currency_symbol": "€",
        "display_symbol": True,
    }


@pytest.mark.version("V2")
@pytest.mark.usefixtures("config")
def test_api_key_is_taken_from_the_config_when_not_provided(client, answer):
    answer("1")

    prompt_for_budget()

    assert client.call_args.args[0] == "my-api-key"


@pytest.mark.version("missing")
@pytest.mark.usefixtures("config")
def test_no_api_key_and_no_config_is_an_error(client, answer):
    answer("1")

    with pytest.raises(RuntimeError, match="Could not find config"):
        prompt_for_budget()


@pytest.mark.parametrize(
    "budget_details, expected_message",
    [
        pytest.param(None, "Could not find budget with ID", id="budget_missing"),
        pytest.param(
            plan_detail(currency_format=None),
            "has no currency format",
            id="currency_format_missing",
        ),
        pytest.param(plan_detail(date_format=None), "has no date format", id="date_format_missing"),
    ],
)
def test_incomplete_budget_details_are_rejected(
    client, answer, budget_details: PlanDetail | None, expected_message: str
):
    client.return_value.budget.return_value = budget_details
    answer("1")

    with pytest.raises(ValueError, match=expected_message):
        prompt_for_budget(api_key="an-api-key")


@pytest.mark.xfail(
    reason=(
        "utils.py:53 passes a generator to console().print, so the user is asked to pick a "
        "budget by number without ever seeing the numbered list"
    ),
    strict=True,
)
def test_budget_names_are_listed_before_asking_for_a_number(client, answer, capsys):
    answer("1")

    prompt_for_budget(api_key="an-api-key")

    output = capsys.readouterr().out
    assert "First Budget" in output
    assert "Second Budget" in output
