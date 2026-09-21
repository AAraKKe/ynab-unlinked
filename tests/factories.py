# type: ignore
import datetime as dt
import uuid

import factory
from factory.base import Factory
from ynab import Account, DateFormat, PlanDetail, TransactionClearedStatus, TransactionDetail
from ynab import CurrencyFormat as SdkCurrencyFormat

from ynab_unlinked.config.models.v2 import CurrencyFormat
from ynab_unlinked.models import PendingImport, Transaction

# Matches the `today` fixture so factory built objects line up with frozen time
DEFAULT_DATE = dt.date(2025, 5, 15)


class CurrencyFormatFactory(Factory):
    class Meta:
        model = CurrencyFormat

    iso_code = "EUR"
    decimal_digits = 2
    decimal_separator = "."
    symbol_first = False
    group_separator = ","
    currency_symbol = "€"
    display_symbol = True


class TransactionFactory(Factory):
    class Meta:
        model = Transaction

    date = DEFAULT_DATE
    payee = "Mercadona"
    amount = -10.0


class PendingImportFactory(Factory):
    """A transaction paired with the ids YNAB recognises it by.

    The ids are set literally so a test can pin what the client forwards without depending on
    how `assign_import_ids` derives them.
    """

    class Meta:
        model = PendingImport

    class Params:
        date = DEFAULT_DATE
        payee = "Mercadona"
        amount = -10.0

    transaction = factory.LazyAttribute(
        lambda o: TransactionFactory(date=o.date, payee=o.payee, amount=o.amount)
    )
    import_id = factory.LazyAttribute(
        lambda o: f"YNAB:{round(o.transaction.amount * 1000)}:{o.transaction.date:%Y-%m-%d}:1"
    )
    legacy_import_id = "0" * 30


class TransactionDetailFactory(Factory):
    """A transaction as YNAB returns it. `amount` is in milliunits, not currency units."""

    class Meta:
        model = TransactionDetail

    id = "ynab-1"
    var_date = DEFAULT_DATE
    amount = -10000
    cleared = TransactionClearedStatus.CLEARED
    approved = True
    account_id = uuid.UUID(int=1)
    account_name = "Checking"
    deleted = False
    payee_name = "Mercadona"
    payee_id = None
    import_id = None
    subtransactions = factory.LazyFunction(list)


class AccountFactory(Factory):
    """An open on-budget account. Its id renders as ...00a."""

    class Meta:
        model = Account

    id = uuid.UUID(int=10)
    name = "Checking"
    type = "checking"
    on_budget = True
    closed = False
    balance = 0
    cleared_balance = 0
    uncleared_balance = 0
    transfer_payee_id = uuid.UUID(int=11)
    deleted = False


class SdkCurrencyFormatFactory(Factory):
    """The currency format as the YNAB SDK returns it, not the one stored in the config."""

    class Meta:
        model = SdkCurrencyFormat

    iso_code = "EUR"
    decimal_digits = 2
    decimal_separator = "."
    symbol_first = False
    group_separator = ","
    currency_symbol = "€"
    display_symbol = True
    example_format = "€1,234.56"


class PlanDetailFactory(Factory):
    """A budget with all its details, as YNAB returns it. Its id renders as ...001."""

    class Meta:
        model = PlanDetail

    id = uuid.UUID(int=1)
    name = "My Budget"
    date_format = factory.LazyFunction(lambda: DateFormat(format="DD/MM/YYYY"))
    currency_format = factory.SubFactory(SdkCurrencyFormatFactory)
