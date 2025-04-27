import unidecode

from rapidfuzz import fuzz

from ynab.models.transaction_detail import TransactionDetail
from ynab.models.transaction_cleared_status import TransactionClearedStatus
from ynab_unlinked.models import TransactionWithYnabData
from ynab_unlinked.client import Client


TIME_WINDOW_MATCH_DAYS = 2
FUZZY_MATCH_THRESHOLD = 98


def preprocess_payee(value: str) -> str:
    result = value.lower()
    return unidecode.unidecode(result)


def match_transactions(
    transactions: list[TransactionWithYnabData],
    ynab_transactions: list[TransactionDetail],
    reconcile: bool,
):
    """Add transacation id to the transaction if it is found in ynab"""

    def match_single_transaction(transaction: TransactionWithYnabData):
        for t in ynab_transactions:
            if t.payee_name is None:
                continue

            date_window = (
                abs((t.var_date - transaction.date).days) <= TIME_WINDOW_MATCH_DAYS
            )

            fuzz_raio = fuzz.partial_ratio(
                transaction.payee,
                t.payee_name,
                score_cutoff=FUZZY_MATCH_THRESHOLD,
                processor=preprocess_payee,
            )
            similar_payee = fuzz_raio > 0

            same_amount = t.amount / 1000 == transaction.amount

            if date_window and similar_payee and same_amount:
                transaction.ynab_id = t.id
                transaction.cleared = t.cleared  # Remove the default value
                # If it is uncleared, clear it
                if t.cleared is TransactionClearedStatus.UNCLEARED:
                    transaction.cleared = TransactionClearedStatus.CLEARED

                # If we are requesting to reconcile matching transactions, set them
                if reconcile:
                    transaction.cleared = TransactionClearedStatus.RECONCILED

                # Mark for update any update on the cleared status
                if transaction.cleared is not t.cleared:
                    transaction.needs_update = True
                return

    for t in transactions:
        match_single_transaction(t)


def add_payee(transactions: list[TransactionWithYnabData], client: Client):
    """Try to identify the payee in the transaction with an existing payee in YNAB"""
    payees = client.payees()

    def match_payee(transaction: TransactionWithYnabData):
        for p in payees:
            if (
                fuzz.partial_ratio(
                    transaction.payee,
                    p.name,
                    score_cutoff=FUZZY_MATCH_THRESHOLD,
                    processor=preprocess_payee,
                )
                > 0
            ):
                transaction.ynab_payee = p.name
                transaction.ynab_payee_id = p.id
                return
        transaction.ynab_payee = transaction.payee

    for t in transactions:
        match_payee(t)


def augmnet_transactions(
    transactions: list[TransactionWithYnabData],
    ynab_transactions: list[TransactionDetail],
    client: Client,
    reconcile: bool,
):
    match_transactions(transactions, ynab_transactions, reconcile)
    add_payee(transactions, client)
