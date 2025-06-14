# type: ignore
from factory.base import Factory

from ynab_unlinked.config.models.v2 import CurrencyFormat


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
