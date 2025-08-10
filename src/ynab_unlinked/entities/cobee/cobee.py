from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, assert_never

if TYPE_CHECKING:
    from pathlib import Path

    from ynab_unlinked.context_object import YnabUnlinkedContext
    from ynab_unlinked.models import Transaction

DATE_REGEX = re.compile(r"(\d{1,2}) (\w{3}) (\d{4})")

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
class CobeeContext:
    language: Language


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
        case never:
            assert_never(never)


class Cobee:
    def parse(
        self, input_file: Path, context: YnabUnlinkedContext[CobeeContext]
    ) -> list[Transaction]:
        # Import now the html parser
        import html_text

        from ynab_unlinked.models import Transaction

        text = html_text.extract_text(input_file.read_text())  # type: ignore

        start = False
        previous_line = ""
        transactions: list[Transaction] = []
        date: dt.date | None = None
        payee: str | None = None
        amount: float | None = None
        identifiers = identifers_by_language(context.extras.language)

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
                amount_str = line.replace("€", "").replace(",", ".")

                try:
                    amount = float(amount_str)
                    if amount == 0:
                        continue
                except ValueError:
                    # If we could not convert this to float it means this is not an amount line.
                    continue

                # If it was the amount line, the previous line is the payee.
                payee = previous_line

                if date is None or payee is None:
                    raise ValueError(
                        f"The input file is not valid. The amount {amount} has been found without a date or payee."
                    )

                # If the payee is the accumulation line, we should skip it
                if payee == identifiers.accumulation:
                    continue

                transactions.append(Transaction(date=date, payee=payee, amount=amount))
                continue

            if identifiers.cancelled in line or identifiers.rejected in line:
                # These are transactions that didn't went through.
                transactions.pop()
                continue

            previous_line = line

        return transactions

    def name(self) -> str:
        return "cobee"
