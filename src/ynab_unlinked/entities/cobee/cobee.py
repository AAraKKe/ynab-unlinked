import re
import datetime as dt
from enum import Enum, auto
from pathlib import Path

from ynab_unlinked.context_object import YnabUnlinkedContext
from ynab_unlinked.models import Transaction


class ParseState(Enum):
    DATE = auto()
    PAYEE = auto()
    AMOUNT = auto()


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


def parse_date(date_str: str) -> dt.date | None:
    if (groups := DATE_REGEX.match(date_str)) is None:
        return None

    day, month, year = groups.groups()

    if month not in MONTHS_NUMBERS:
        raise ValueError(f"The month {month} is not valid.")

    month = MONTHS_NUMBERS[month]

    return dt.date(int(year), int(month), int(day))


class Cobee:
    def parse(self, input_file: Path, context: YnabUnlinkedContext) -> list[Transaction]:
        # Import now the html parser
        import html_text

        text = html_text.extract_text(input_file.read_text())  # type: ignore

        start = False
        state = ParseState.DATE
        transactions: list[Transaction] = []
        date: dt.date | None = None
        payee: str | None = None
        amount: float | None = None

        for line in text.splitlines():
            if not line:
                continue

            if "Transacciones" in line:
                start = True
                continue

            if not start:
                continue

            if state is ParseState.DATE:
                if (date := parse_date(line.strip())) is None:
                    continue

                state = ParseState.PAYEE
                continue

            if state is ParseState.PAYEE:
                payee = line.strip()
                state = ParseState.AMOUNT
                continue

            if state is ParseState.AMOUNT:
                amount_str = line.strip().replace("€", "").replace(",", ".")
                if not amount_str:
                    continue

                amount = float(amount_str)
                if date is None or payee is None:
                    raise ValueError(
                        f"The input file is not valid. The amount {amount} has been found without a date or payee."
                    )

                transactions.append(Transaction(date=date, payee=payee, amount=amount))

                state = ParseState.DATE

        return transactions

    def name(self) -> str:
        return "cobee"
