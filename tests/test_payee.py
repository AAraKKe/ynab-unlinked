import uuid
from collections.abc import Callable
from types import SimpleNamespace

import pytest
from ynab import Payee

from tests.factories import (
    PayeeFactory,
    TransactionDetailFactory,
    TransactionWithYnabDataFactory,
)
from tests.helpers.ynab_api import YnabClientStub
from ynab_unlinked.config import ConfigV2
from ynab_unlinked.payee import payee_matches, set_payee_from_ynab
from ynab_unlinked.ynab_api import Client

pytestmark = pytest.mark.version("V2")

ClientBuilder = Callable[[list[Payee]], Client]


@pytest.fixture
def client_with_payees(ynab_api: YnabClientStub) -> ClientBuilder:
    def register(payees: list[Payee]) -> Client:
        ynab_api.api("payees").get_payees.return_value = SimpleNamespace(
            data=SimpleNamespace(payees=payees)
        )
        return Client(api_key="someapikey")

    return register


@pytest.mark.parametrize(
    ("bank_payee", "ynab_name", "expected"),
    [
        pytest.param("Mercadona", "Mercadona", True, id="an identical name matches"),
        pytest.param("MERCADONA", "mercadona", True, id="case is ignored"),
        pytest.param("Cafe Nino", "Café Niño", True, id="accents are ignored"),
        pytest.param("El Corte Ingles", "El  Corte   Inglés", True, id="spacing is ignored"),
        pytest.param("MERCADONA S.A.", "Mercadona SA", True, id="punctuation survives the cutoff"),
        pytest.param("Netflix", "Netflix.com", True, id="a domain suffix still matches"),
        pytest.param(
            "COMPRA EN REPSOL GASOLINERA",
            "Repsol",
            True,
            id="the bank prefix and suffix around a known payee are ignored",
        ),
        pytest.param("Mercadona", "Mercabona", False, id="one letter off falls below the cutoff"),
        pytest.param("Mercadona", "Carrefour", False, id="two unrelated supermarkets do not match"),
        pytest.param("Lidl", "Aldi", False, id="the same letters in another order do not match"),
        pytest.param("Netflix", "Spotify", False, id="two unrelated services do not match"),
    ],
)
def test_payee_matches_fuzzily(
    bank_payee: str, ynab_name: str, expected: bool, config_v2: ConfigV2
):
    transaction = TransactionWithYnabDataFactory(payee=bank_payee)

    assert payee_matches(transaction, config_v2, PayeeFactory(name=ynab_name)) is expected


@pytest.mark.parametrize(
    ("payee_source", "expected"),
    [
        pytest.param(PayeeFactory(name="Mercadona"), True, id="a ynab payee is read from its name"),
        pytest.param(
            TransactionDetailFactory(payee_name="Mercadona"),
            True,
            id="a ynab transaction is read from its payee name",
        ),
        pytest.param(
            TransactionDetailFactory(payee_name=None),
            False,
            id="a ynab transaction without a payee never matches",
        ),
    ],
)
def test_payee_matches_accepts_both_payee_sources(
    payee_source: object, expected: bool, config_v2: ConfigV2
):
    transaction = TransactionWithYnabDataFactory(payee="MERCADONA 4412")

    assert payee_matches(transaction, config_v2, payee_source) is expected


@pytest.mark.parametrize(
    ("ynab_name", "expected"),
    [
        pytest.param("My Payee", True, id="the name the rule renames to matches"),
        pytest.param("My Other Payee", False, id="another renamed payee does not match"),
    ],
)
def test_payee_matches_uses_a_configured_rename_rule(
    ynab_name: str, expected: bool, config_v2: ConfigV2
):
    # "Something weird" -> "My Payee" only exists as a rule in the config; the two names share
    # nothing, so a match here can only come from the rule lookup.
    transaction = TransactionWithYnabDataFactory(payee="Something weird")

    assert payee_matches(transaction, config_v2, PayeeFactory(name=ynab_name)) is expected


@pytest.mark.xfail(
    reason=(
        "payee.py:52 uses fuzz.partial_ratio, which scores any substring at 100. A short bank "
        "payee therefore matches every unrelated YNAB payee that happens to contain it, and "
        "matcher.py promotes that to a full MATCHED without asking the user"
    ),
    strict=True,
)
@pytest.mark.parametrize(
    "bank_payee",
    [
        pytest.param("A", id="a single letter matches anything containing it"),
        pytest.param("Mar", id="three letters match the middle of another name"),
        pytest.param("Sol", id="three letters match the end of another name"),
    ],
)
def test_short_payees_do_not_match_unrelated_names(bank_payee: str, config_v2: ConfigV2):
    transaction = TransactionWithYnabDataFactory(payee=bank_payee)

    assert not payee_matches(transaction, config_v2, PayeeFactory(name="Carrefour Market Solar"))


@pytest.mark.parametrize(
    ("bank_payee", "expected_calls"),
    [
        pytest.param("Something weird", 0, id="a rename rule short circuits the payee lookup"),
        pytest.param("Mercadona", 1, id="anything else falls through to the payee list"),
    ],
)
def test_the_payee_list_is_fetched_only_when_no_rule_applies(
    bank_payee: str, expected_calls: int, config_v2: ConfigV2, client_with_payees: ClientBuilder
):
    transactions = [TransactionWithYnabDataFactory(payee=bank_payee) for _ in range(3)]
    client = client_with_payees([PayeeFactory(name="Unrelated")])

    set_payee_from_ynab(transactions, client, config_v2)

    assert client.api("payees").get_payees.call_count == expected_calls


def test_a_rename_rule_renames_the_payee(config_v2: ConfigV2, client_with_payees: ClientBuilder):
    transaction = TransactionWithYnabDataFactory(payee="Something weird")

    set_payee_from_ynab([transaction], client_with_payees([]), config_v2)

    assert transaction.ynab_payee == "My Payee"


@pytest.mark.parametrize(
    ("bank_payee", "expected_payee", "expected_id"),
    [
        pytest.param(
            "COMPRA MERCADONA 4412",
            "Mercadona",
            str(uuid.UUID(int=42)),
            id="a matching ynab payee replaces the bank name",
        ),
        pytest.param(
            "Kiosko de la esquina",
            "Kiosko de la esquina",
            None,
            id="the bank name is kept when nothing matches",
        ),
    ],
)
def test_the_payee_is_resolved_against_the_ynab_payee_list(
    bank_payee: str,
    expected_payee: str,
    expected_id: str | None,
    config_v2: ConfigV2,
    client_with_payees: ClientBuilder,
):
    transaction = TransactionWithYnabDataFactory(payee=bank_payee)
    client = client_with_payees(
        [PayeeFactory(name="Carrefour"), PayeeFactory(name="Mercadona", id=uuid.UUID(int=42))]
    )

    set_payee_from_ynab([transaction], client, config_v2)

    assert transaction.ynab_payee == expected_payee
    assert transaction.ynab_payee_id == expected_id


@pytest.mark.parametrize(
    ("partial_payee_id", "expected_id"),
    [
        pytest.param(
            uuid.UUID(int=99), str(uuid.UUID(int=99)), id="the partial match carries an id"
        ),
        pytest.param(None, None, id="the partial match has no id"),
    ],
)
def test_a_partial_match_wins_over_the_payee_list(
    partial_payee_id: uuid.UUID | None,
    expected_id: str | None,
    config_v2: ConfigV2,
    client_with_payees: ClientBuilder,
):
    transaction = TransactionWithYnabDataFactory(payee="Mercadona")
    transaction.partial_match = TransactionDetailFactory(
        payee_name="Supermercado del barrio", payee_id=partial_payee_id
    )
    client = client_with_payees([PayeeFactory(name="Mercadona", id=uuid.UUID(int=1))])

    set_payee_from_ynab([transaction], client, config_v2)

    assert transaction.ynab_payee == "Supermercado del barrio"
    assert transaction.ynab_payee_id == expected_id
