from typing import overload

import unidecode
from rapidfuzz import fuzz
from ynab.models.payee import Payee
from ynab.models.transaction_detail import TransactionDetail

from ynab_unlinked.config import ConfigV2
from ynab_unlinked.models import TransactionWithYnabData
from ynab_unlinked.ynab_api import Client

FUZZY_MATCH_THRESHOLD = 90


def __preprocess_payee(value: str) -> str:
    result = value.lower().replace(" ", "")
    return unidecode.unidecode(result)


@overload
def payee_matches(
    transaction: TransactionWithYnabData,
    config: ConfigV2,
    payee_source: TransactionDetail,
) -> bool: ...


@overload
def payee_matches(
    transaction: TransactionWithYnabData, config: ConfigV2, payee_source: Payee
) -> bool: ...


def payee_matches(
    transaction: TransactionWithYnabData,
    config: ConfigV2,
    payee_source: TransactionDetail | Payee,
) -> bool:
    if isinstance(payee_source, TransactionDetail):
        if payee_source.payee_name is None:
            return False
        payee_name = payee_source.payee_name
    else:
        payee_name = payee_source.name

    if payee_name == transaction.payee:
        return True

    if config.payee_from_fules(transaction.payee) == payee_name:
        return True

    return (
        fuzz.partial_ratio(
            transaction.payee,
            payee_name,
            score_cutoff=FUZZY_MATCH_THRESHOLD,
            processor=__preprocess_payee,
        )
        > 0
    )


def __match_from_payee_list(
    transaction: TransactionWithYnabData, payees: list[Payee], config: ConfigV2
):
    # If we have a partial match, use it
    if transaction.partial_match is not None:
        transaction.ynab_payee = transaction.partial_match.payee_name
        transaction.ynab_payee_id = transaction.partial_match.payee_id
        return

    for p in payees:
        if payee_matches(transaction, config, p):
            transaction.ynab_payee = p.name
            transaction.ynab_payee_id = p.id
            return

    transaction.ynab_payee = transaction.payee


def set_payee_from_ynab(
    transactions: list[TransactionWithYnabData], client: Client, config: ConfigV2
):
    """
    Compare each transaction payee with an existing YNAB payee and set the payee from YNAB if a match is found
    """
    payees = None
    for t in transactions:
        # First check if we have previous naming rules
        if payee := config.payee_from_fules(t.payee):
            t.ynab_payee = payee
            continue

        # Only call once but do not call unless we have not found a match
        if payees is None:
            payees = client.payees(budget_id=config.budget.id)

        __match_from_payee_list(t, payees, config)
