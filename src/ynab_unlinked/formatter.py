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

    def format_amount(
        self, amount: float, positive_style: str = "", negative_style: str = ""
    ) -> str:
        sign = "-" if amount < 0 else ""
        style = negative_style if amount < 0 else positive_style
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
            formatted = f"{sign}{amount_str}"
        elif self.currency_format.symbol_first:
            formatted = f"{sign}{self.currency_format.currency_symbol}{amount_str}"
        else:
            formatted = f"{sign}{amount_str}{self.currency_format.currency_symbol}"

        return f"{style}{formatted}{end_style}"

    def format_amount_milli(self, milli_amount: int) -> str:
        amount = milli_amount / 1000.0
        return self.format_amount(amount)

    def format_flow(self, amount: float) -> str:
        """An amount in a list of transactions: money in carries a `+`, money out its `-`.

        The sign says the direction even where the colour of an inflow is lost (a terminal
        without colour, a colour blind reader). Balances and totals use `format_amount`.
        """
        amount = round(amount, self.currency_format.decimal_digits)
        text = self.format_amount(amount)
        return f"+{text}" if amount > 0 else text

    def is_inflow(self, amount: float) -> bool:
        """Whether `format_flow` shows `amount` as money in: positive once rounded to the
        currency's digits, so a sub-cent amount is neither green nor signed."""
        return round(amount, self.currency_format.decimal_digits) > 0
