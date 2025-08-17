from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import datetime as dt
    from pathlib import Path

    from ynab_unlinked.context_object import YnabUnlinkedContext
    from ynab_unlinked.models import Transaction


# Line that triggers the credit operations
ANCHOR_LINE = "Límite de crédito".encode("cp1252").decode("cp1252")
XLS_DEBIT_LINE = "MOVIMIENTOS DE DEBITO"
TRANSACTION_PATTERN = re.compile(r"^(\d{2}/\d{2})\|(.+?)\|.+?\|(\d+.*EUR)(\([\d*]\))?$")


class SabadellParser:
    def parse(self, input_file: Path, context: YnabUnlinkedContext) -> list[Transaction]:
        from ynab_unlinked.entities import InputType
        from ynab_unlinked.utils import extract_type

        input_type = extract_type(input_file, valid=[InputType.TXT, InputType.XLS])

        match input_type:
            case InputType.TXT:
                return self.__parse_txt(input_file)
            case InputType.XLS:
                return self.__parse_xls(input_file)
            case _:
                # Should never happen because we already checked
                raise RuntimeError(f"Unexpected input type: {input_type}")

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

        return transactions

    def __parse_xls(self, input_file: Path) -> list[Transaction]:
        from ynab_unlinked.models import Transaction
        from ynab_unlinked.parsers import xls

        # This is the row after which real transactions appear
        row_trigger = ["FECHA", "CONCEPTO", "LOCALIDAD"]

        transactions = []

        for entry in xls(input_file, read_after_row_like=row_trigger, allow_partial_match=True):
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

        return transactions

    def __parse_date(self, raw: str) -> dt.date:
        import datetime as dt

        current_year = dt.date.today().year
        return dt.datetime.strptime(f"{raw}/{current_year}", "%d/%m/%Y").date()

    def __parse_payee(self, raw: str) -> str:
        return raw.title()

    def __parse_amount(self, raw: str) -> float:
        return float(raw.replace("EUR", "").replace(",", "."))

    def name(self) -> str:
        return "sabadell"
