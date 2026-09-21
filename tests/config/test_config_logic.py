import datetime as dt
import json

import pytest

from tests.factories import TransactionDetailFactory, TransactionWithYnabDataFactory
from tests.helpers.config import ConfigFiles
from ynab_unlinked.config import Config
from ynab_unlinked.config.constants import TRANSACTION_GRACE_PERIOD_DAYS
from ynab_unlinked.models import MatchStatus, Transaction, TransactionWithYnabData

# This module tests the central logic of the config object. It does not focus on each particular
# version and instead ensures that the logic that needs to be supported is supported propertly


@pytest.fixture
def stored(config: str, config_files: ConfigFiles):
    """Reads back what the config under test has on disk."""

    def read() -> dict:
        return json.loads(config_files.read(config))

    return read


def test_save(config_obj: Config, stored):
    config_obj.api_key = "some-other-api-key"  # type: ignore

    config_obj.save()

    assert stored()["api_key"] == "some-other-api-key"


def test_update_and_save(config_obj: Config, stored):
    trasaction_date = dt.date(2025, 1, 1)
    transaction = Transaction(date=trasaction_date, payee="Acme Store", amount=-12.34)

    config_obj.update_and_save(transaction, "sabadell")

    sabadell = stored()["entities"]["sabadell"]
    assert dt.datetime.strptime(
        sabadell["checkpoint"]["latest_date_processed"], "%Y-%m-%d"
    ).date() == (trasaction_date - dt.timedelta(days=TRANSACTION_GRACE_PERIOD_DAYS))


def test_payee_rule_is_learned_from_a_partial_match(config_obj: Config, stored):
    config_obj.add_payee_rules(
        [
            TransactionWithYnabDataFactory(
                payee="MERCADONA SL",
                status=MatchStatus.PARTIAL_MATCH,
                partial_match=TransactionDetailFactory(),
                ynab_payee="Mercadona",
            )
        ]
    )

    assert config_obj.payee_rules["Mercadona"] == {"MERCADONA SL"}
    assert stored()["payee_rules"]["Mercadona"] == ["MERCADONA SL"]


def test_payee_rules_accumulate_aliases_for_the_same_ynab_payee(config_obj: Config):
    config_obj.add_payee_rules(
        [
            TransactionWithYnabDataFactory(
                payee="MERCADONA SL",
                status=MatchStatus.PARTIAL_MATCH,
                partial_match=TransactionDetailFactory(),
                ynab_payee="Mercadona",
            ),
            TransactionWithYnabDataFactory(
                payee="MERCADONA BCN",
                status=MatchStatus.PARTIAL_MATCH,
                partial_match=TransactionDetailFactory(),
                ynab_payee="Mercadona",
            ),
        ]
    )

    assert config_obj.payee_rules["Mercadona"] == {"MERCADONA SL", "MERCADONA BCN"}


@pytest.mark.parametrize(
    "transaction",
    [
        pytest.param(
            TransactionWithYnabDataFactory(payee="Mercadona"),
            id="the transaction was never partially matched",
        ),
        pytest.param(
            TransactionWithYnabDataFactory(
                payee="MERCADONA SL",
                status=MatchStatus.PARTIAL_MATCH,
                partial_match=TransactionDetailFactory(payee_name=None),
                ynab_payee=None,
            ),
            id="the ynab payee has no name",
        ),
        pytest.param(
            TransactionWithYnabDataFactory(
                payee="Mercadona",
                status=MatchStatus.PARTIAL_MATCH,
                partial_match=TransactionDetailFactory(),
                ynab_payee="Mercadona",
            ),
            id="both payees are already equal",
        ),
    ],
)
def test_no_payee_rule_is_learned_when_there_is_nothing_to_remember(
    config_obj: Config, stored, transaction: TransactionWithYnabData
):
    rules_before = dict(config_obj.payee_rules)
    on_disk_before = stored()

    config_obj.add_payee_rules([transaction])

    assert config_obj.payee_rules == rules_before
    assert stored() == on_disk_before, "The config was written even though no rule changed"


@pytest.mark.parametrize(
    "payee, expected",
    [
        pytest.param("Something weird", "My Payee", id="known_alias"),
        pytest.param("And this even less", "My Other Payee", id="alias_of_a_multi_alias_rule"),
        pytest.param("My Payee", None, id="ynab_name_is_not_an_alias_of_itself"),
        pytest.param("Unknown Payee", None, id="unknown_payee"),
    ],
)
def test_payee_from_rules(config_obj: Config, payee: str, expected: str | None):
    assert config_obj.payee_from_fules(payee) == expected


@pytest.mark.parametrize(
    "name, expected_account_id",
    [
        pytest.param("sabadell", "sabadell-account", id="known_entity"),
        pytest.param("unknown", None, id="unknown_entity"),
    ],
)
def test_entity_lookup(config_obj: Config, name: str, expected_account_id: str | None):
    entity = config_obj.entity(name)
    assert (entity.account_id if entity is not None else None) == expected_account_id


def test_set_entity_account_updates_a_known_entity(config_obj: Config):
    config_obj.set_entity_account("sabadell", "another-account")

    entity = config_obj.entity("sabadell")
    assert entity is not None
    assert entity.account_id == "another-account"


def test_set_entity_account_ignores_an_unknown_entity(config_obj: Config):
    config_obj.set_entity_account("unknown", "another-account")

    assert config_obj.entity("unknown") is None
