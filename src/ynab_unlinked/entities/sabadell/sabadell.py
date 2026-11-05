from __future__ import annotations

import datetime as dt
import re
from dataclasses import replace
from typing import TYPE_CHECKING, Any

from ynab_unlinked.entities import Match

if TYPE_CHECKING:
    from pathlib import Path

    from ynab_unlinked.context_object import YnabUnlinkedContext
    from ynab_unlinked.models import Transaction


# Line that triggers the credit operations
ANCHOR_LINE = "Límite de crédito".encode("cp1252").decode("cp1252")
XLS_DEBIT_LINE = "MOVIMIENTOS DE DEBITO"
XLS_HEADER = ["FECHA", "CONCEPTO", "LOCALIDAD"]
FUTURE_SLACK = dt.timedelta(days=3)
"""How far past today a row may be dated before it is taken for one of last year. A few days
so that a card payment the bank already dates tomorrow (time zones) keeps its year."""
TRANSACTION_PATTERN = re.compile(r"^(\d{2}/\d{2})\|(.+?)\|.+?\|([-]?\d+.*EUR)(\([\d*]\))?$")


class SabadellParser:
    def __init__(self, year: int):
        self.year = year

    def parse(self, input_file: Path, context: YnabUnlinkedContext[Any]) -> list[Transaction]:
        from ynab_unlinked.entities import InputType
        from ynab_unlinked.entities._sniff import extract_type

        input_type = extract_type(input_file, valid=[InputType.TXT, InputType.XLS])

        match input_type:
            case InputType.TXT:
                return self.__parse_txt(input_file)
            case _:
                return self.__parse_xls(input_file)

    def __parse_txt(self, input_file: Path) -> list[Transaction]:
        from ynab_unlinked.models import Transaction

        lines = input_file.read_text(encoding="cp1252").splitlines()
        start = False
        transactions: list[Transaction] = []
        for line in lines:
            if ANCHOR_LINE in line:
                start = True
                continue

            if not start:
                continue

            if (match := TRANSACTION_PATTERN.match(line)) is not None:
                if len(match.groups()) == 4 and match[4] == "(1)":
                    # Pending transaction
                    continue

                transactions.append(
                    Transaction(
                        date=self.__parse_date(match[1]),
                        payee=self.__parse_payee(match[2]),
                        amount=-self.__parse_amount(match[3]),
                    )
                )

        return self._no_future_dates(self._adjust_year_transition(transactions))

    def __parse_xls(self, input_file: Path) -> list[Transaction]:
        from ynab_unlinked.models import Transaction
        from ynab_unlinked.parsers import xls

        transactions: list[Transaction] = []

        # Real transactions appear after the header row
        for entry in xls(input_file, read_after_row_like=XLS_HEADER, allow_partial_match=True):
            # If we find debit movements, stop reading
            # Debit movements appear at the end of the file
            if entry[0] == XLS_DEBIT_LINE:
                break

            # The order is date, payee, x, x, value, EUR
            date, payee, amount, currency = entry[0], entry[1], entry[4], entry[5]

            # If currency ends in (1) is a pending transaction, skip
            if currency.endswith("(1)"):
                continue

            # If we cannot parse the date, then continue because we might be in an entry that is not a
            # transaction entry
            try:
                parsed_date = self.__parse_date(date)
            except Exception:
                continue

            transactions.append(
                Transaction(
                    date=parsed_date,
                    payee=self.__parse_payee(payee),
                    amount=-self.__parse_amount(amount),
                )
            )

        return self._no_future_dates(self._adjust_year_transition(transactions))

    def _adjust_year_transition(self, transactions: list[Transaction]) -> list[Transaction]:
        """
        Adjust transactions dates when a year transition is detected.

        Sabadell files do not include the year in the date. When importing a file that contains
        transactions from December and January, we need to infer the year.

        If we find transactions in January and December, we assume that the December transactions
        belong to the previous year.
        """
        months = {t.date.month for t in transactions}
        if 1 not in months or 12 not in months:
            return transactions

        return [
            replace(t, date=t.date.replace(year=t.date.year - 1)) if t.date.month == 12 else t
            for t in transactions
        ]

    def _no_future_dates(self, transactions: list[Transaction]) -> list[Transaction]:
        """Move rows dated after today back one year.

        A December only statement exported in January is dated in the new year when the
        year is the current one, which YNAB refuses as future dates (and a forced year
        would give other import ids than the right one).
        """
        latest = dt.date.today() + FUTURE_SLACK
        return [
            replace(t, date=_previous_year(t.date)) if t.date > latest else t for t in transactions
        ]

    def __parse_date(self, raw: str) -> dt.date:
        current_year = self.year
        return dt.datetime.strptime(f"{raw}/{current_year}", "%d/%m/%Y").date()

    def __parse_payee(self, raw: str) -> str:
        return raw.title()

    def __parse_amount(self, raw: str) -> float:
        from ynab_unlinked.parsers import parse_amount

        return parse_amount(raw)

    def name(self) -> str:
        return "sabadell"

    def sniff(self, input_file: Path) -> Match:
        from ynab_unlinked.entities._sniff import guarded

        return guarded(self.__sniff, input_file)

    def __sniff(self, input_file: Path) -> Match:
        from ynab_unlinked.entities import InputType
        from ynab_unlinked.entities._sniff import first_rows, head, suffix, wrong_suffix

        if (mismatch := wrong_suffix(input_file, [InputType.TXT, InputType.XLS])) is not None:
            return mismatch

        if suffix(input_file) == InputType.TXT:
            try:
                text = head(input_file).decode("cp1252")
            except UnicodeDecodeError:
                return Match(0.0, "Not a Sabadell text statement, it is not cp1252 text")
            if ANCHOR_LINE not in text:
                return Match(0.0, "No credit limit line found")
            if any(TRANSACTION_PATTERN.match(line) for line in text.splitlines()):
                return Match(0.95, "Credit limit line and Sabadell operations found")
            return Match(0.3, "Credit limit line found but no operation")

        rows = [[str(cell) for cell in row] for row in first_rows(input_file)]
        if any(row[: len(XLS_HEADER)] == XLS_HEADER for row in rows):
            return Match(0.9, "Sabadell movements header found")
        if any(XLS_DEBIT_LINE in row for row in rows):
            return Match(0.6, "Sabadell debit movements section found")
        return Match(0.0, "Sabadell movements header not found")


def _previous_year(date: dt.date) -> dt.date:
    try:
        return date.replace(year=date.year - 1)
    except ValueError:
        # 29 February, which the year before does not have: it cannot be last year's row
        return date
