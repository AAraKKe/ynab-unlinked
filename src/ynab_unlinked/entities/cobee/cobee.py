from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from ynab_unlinked.entities import Match

if TYPE_CHECKING:
    from pathlib import Path

    from ynab_unlinked.models import Transaction

DATE_REGEX = re.compile(r"(\d{1,2}) (\w{3}) (\d{4})")

# A saved page inlines the styles and scripts of the app before the transaction list, so the
# sniff reads further into an HTML file than the 64 KB it reads elsewhere
SNIFF_BYTES = 2 * 1024 * 1024

# Needed to parse the date. Cobee is a Spanish system for work benefits but the
# dates are in English locale. Parsing dates with something other than numbers
# does not seem to be supported in Babel.
MONTHS_NUMBERS = {
    "Jan": 1,
    "Feb": 2,
    "Mar": 3,
    "Apr": 4,
    "May": 5,
    "Jun": 6,
    "Jul": 7,
    "Aug": 8,
    "Sep": 9,
    "Oct": 10,
    "Nov": 11,
    "Dec": 12,
}


class Language(StrEnum):
    ES = "es"
    EN = "en"
    PT = "pt"


@dataclass
class Identifiers:
    transactions_line: str
    rejected: str
    cancelled: str
    # These are the transactions that adds to the wallet
    # Should be ignored since additions should be handled from payroll
    accumulation: str


def parse_date(date_str: str) -> dt.date | None:
    if (groups := DATE_REGEX.match(date_str)) is None:
        return None

    day, month, year = groups.groups()

    if month not in MONTHS_NUMBERS:
        raise ValueError(f"The month {month} is not valid.")

    month = MONTHS_NUMBERS[month]

    return dt.date(int(year), int(month), int(day))


def identifers_by_language(language: Language) -> Identifiers:
    match language:
        case Language.ES:
            return Identifiers(
                transactions_line="Transacciones",
                rejected="Rechazada",
                cancelled="Anulada",
                accumulation="Acumulación en tarjeta",
            )
        case Language.EN:
            return Identifiers(
                transactions_line="Transactions",
                rejected="Rejected",
                cancelled="Cancelled",
                accumulation="Accumulation on card",
            )
        case Language.PT:
            return Identifiers(
                transactions_line="Transações",
                rejected="Recusada",
                cancelled="Anulada",
                accumulation="Acumulado em cartão",
            )


class Cobee:
    def __init__(self, language: Language):
        self.language = language
        """The language the page was saved in: its headings and markers are localised."""

    def parse(self, input_file: Path) -> list[Transaction]:
        # Import now the html parser
        import html_text

        from ynab_unlinked.models import Transaction
        from ynab_unlinked.parsers import parse_amount

        text = html_text.extract_text(input_file.read_text())

        start = False
        previous_line = ""
        # A cancelled or rejected marker refers to the transaction right above it, so it
        # only removes one that has just been read
        last_line_was_transaction = False
        transactions: list[Transaction] = []
        date: dt.date | None = None
        payee: str | None = None
        amount: float | None = None
        identifiers = identifers_by_language(self.language)

        for line in text.splitlines():
            line = line.strip()

            if not line:
                continue

            if identifiers.transactions_line in line:
                start = True
                continue

            if not start:
                continue

            if (try_date := parse_date(line)) is not None:
                date = try_date

            if "€" in line:
                try:
                    amount = parse_amount(line)
                except ValueError:
                    # If we could not convert this to float it means this is not an amount line.
                    continue

                if amount == 0:
                    continue

                # If it was the amount line, the previous line is the payee.
                payee = previous_line

                if date is None:
                    raise ValueError(
                        f"The input file is not valid. The amount {amount} has been found without a date or payee."
                    )

                # If the payee is the accumulation line, we should skip it
                if payee == identifiers.accumulation:
                    continue

                transactions.append(Transaction(date=date, payee=payee, amount=amount))
                last_line_was_transaction = True
                continue

            if identifiers.cancelled in line or identifiers.rejected in line:
                # These are transactions that didn't went through.
                if last_line_was_transaction:
                    transactions.pop()
                    last_line_was_transaction = False
                continue

            previous_line = line
            last_line_was_transaction = False

        return transactions

    def name(self) -> str:
        return "cobee"

    def sniff(self, input_file: Path) -> Match:
        from ynab_unlinked.entities._sniff import guarded

        return guarded(self.__sniff, input_file)

    def __sniff(self, input_file: Path) -> Match:
        import html_text

        from ynab_unlinked.entities import InputType
        from ynab_unlinked.entities._sniff import head, wrong_suffix
        from ynab_unlinked.parsers import parse_amount

        if (mismatch := wrong_suffix(input_file, [InputType.HTML])) is not None:
            return mismatch

        raw = head(input_file, SNIFF_BYTES).decode("utf-8", errors="replace")
        text: str = html_text.extract_text(raw)

        headings = {
            language: position
            for language in Language
            if (position := text.find(identifers_by_language(language).transactions_line)) >= 0
        }
        if not headings:
            return Match(0.0, "No Cobee transactions heading found")

        # The heading that comes first is the one the parser starts reading from
        language = min(headings, key=lambda found: headings[found])

        def is_amount(line: str) -> bool:
            try:
                parse_amount(line)
            except ValueError:
                return False
            return True

        if any("€" in line and is_amount(line.strip()) for line in text.splitlines()):
            return Match(0.9, f"Cobee transactions heading and amounts found (language={language})")
        return Match(0.3, f"Cobee transactions heading found but no amount (language={language})")
