from ynab.models.transaction_detail import TransactionDetail

from ynab_unlinked.config import ConfigV2
from ynab_unlinked.models import MatchStatus, TransactionWithYnabData
from ynab_unlinked.payee import payee_matches

TIME_WINDOW_MATCH_DAYS = 10


def __match_date(transaction: TransactionWithYnabData, ynab_transaction: TransactionDetail) -> bool:
    return abs((ynab_transaction.var_date - transaction.date).days) <= TIME_WINDOW_MATCH_DAYS


def __match_amount(
    transaction: TransactionWithYnabData, ynab_transaction: TransactionDetail
) -> bool:
    return ynab_transaction.amount / 1000 == transaction.amount


def __match_single_transaction(
    transaction: TransactionWithYnabData,
    ynab_transactions: list[TransactionDetail],
    ynab_matched: set[str],
    reconcile: bool,
    config: ConfigV2,
):
    for ynab_transaction in ynab_transactions:
        if ynab_transaction.id in ynab_matched:
            continue

        date_window = __match_date(transaction, ynab_transaction)
        similar_payee = payee_matches(transaction, config, ynab_transaction)
        same_amount = __match_amount(transaction, ynab_transaction)

        if date_window and same_amount:
            ynab_matched.add(ynab_transaction.id)
            return __finalize_match(transaction, ynab_transaction, reconcile, similar_payee)


def __finalize_match(
    transaction: TransactionWithYnabData,
    ynab_transaction: TransactionDetail,
    reconcile: bool,
    similar_payee: bool,
):
    transaction.ynab_id = ynab_transaction.id
    # Keep track of the status before the match
    transaction.ynab_cleared = ynab_transaction.cleared
    transaction.partial_match = ynab_transaction

    # Update clared status based on the current status from ynab
    transaction.update_cleared_from_ynab(ynab_transaction, reconcile)

    # If we are able to match the payee then we mark them as matched right away
    transaction.match_status = MatchStatus.MATCHED if similar_payee else MatchStatus.PARTIAL_MATCH
    return


def match_transactions(
    transactions: list[TransactionWithYnabData],
    ynab_transactions: list[TransactionDetail],
    reconcile: bool,
    config: ConfigV2,
):
    """Match imported transactions to existing YNAB transactions"""

    # This keep track of ynab transactions already matched
    # The intention is that if a transaction on the same date, payee and amount
    # happens twice, we do not match different imported transaction
    # to a single existing transaction in YNAB
    ynab_matched: set[str] = set()

    for transaction in transactions:
        __match_single_transaction(transaction, ynab_transactions, ynab_matched, reconcile, config)
