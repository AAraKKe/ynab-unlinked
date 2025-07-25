import datetime as dt

from ynab_unlinked.config.models.v2 import CurrencyFormat


class Formatter:
    def __init__(self, date_format: str, currency_format: CurrencyFormat):
        self.date_format = date_format
        self.py_date_format = (
            date_format.replace("YYYY", "%Y").replace("MM", "%m").replace("DD", "%d")
        )
        self.currency_format = currency_format

    def format_date(self, date: dt.date) -> str:
        return date.strftime(self.py_date_format)

    def format_amount(self, amount: float, positive_style="", negative_style="") -> str:
        sign = "-" if amount < 0 else ""
        style = positive_style if amount > 0 else negative_style
        end_style = ""
        if style:
            end_style = f"[/{style}]"
            style = f"[{style}]"

        amount = abs(amount)
        amount_str = (
            f"{amount:,.{self.currency_format.decimal_digits}f}".replace(",", "G")
            .replace(".", "D")
            .replace("G", self.currency_format.group_separator)
            .replace("D", self.currency_format.decimal_separator)
        )
        if not self.currency_format.display_symbol:
            return f"{sign}{amount_str}"

        if self.currency_format.symbol_first:
            return f"{sign}{self.currency_format.currency_symbol}{amount_str}"
        return f"{style}{sign}{amount_str}{self.currency_format.currency_symbol}{end_style}"

    def format_amount_milli(self, milli_amount: int) -> str:
        amount = milli_amount / 1000.0
        return self.format_amount(amount)
