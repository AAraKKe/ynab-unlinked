from ynab import TransactionClearedStatus, TransactionDetail

from ynab_unlinked.models import MatchStatus, TransactionWithYnabData
from ynab_unlinked.payee import payee_matches

TIME_WINDOW_MATCH_DAYS = 5


def __match_date(
    transaction: TransactionWithYnabData, ynab_transaction: TransactionDetail
) -> bool:
    return (
        abs((ynab_transaction.var_date - transaction.date).days)
        <= TIME_WINDOW_MATCH_DAYS
    )


def __match_amount(
    transaction: TransactionWithYnabData, ynab_transaction: TransactionDetail
) -> bool:
    return ynab_transaction.amount / 1000 == transaction.amount


def __match_single_transaction(
    transaction: TransactionWithYnabData,
    ynab_transactions: list[TransactionDetail],
    reconcile: bool,
):
    for t in ynab_transactions:
        if t.cleared is TransactionClearedStatus.RECONCILED:
            continue

        date_window = __match_date(transaction, t)
        similar_payee = payee_matches(transaction, t)
        same_amount = __match_amount(transaction, t)

        if date_window and same_amount:
            transaction.ynab_id = t.id
            # Keep track of the status before the match
            transaction.ynab_cleared = t.cleared
            transaction.partial_match = t

            # Update clared status based on the current status from ynab
            transaction.update_cleared_from_ynab(t, reconcile)

            # If we are able to match the payee then we mark them as matched right away
            transaction.match_status = (
                MatchStatus.MATCHED if similar_payee else MatchStatus.PARTIAL_MATCH
            )


def match_transactions(
    transactions: list[TransactionWithYnabData],
    ynab_transactions: list[TransactionDetail],
    reconcile: bool,
):
    """Add transacation id to the transaction if it is found in ynab"""

    for t in transactions:
        __match_single_transaction(t, ynab_transactions, reconcile)
