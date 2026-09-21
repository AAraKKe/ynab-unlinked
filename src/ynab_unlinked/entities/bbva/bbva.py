from __future__ import annotations

from typing import TYPE_CHECKING, cast

from ynab_unlinked.entities import Entity, InputType

if TYPE_CHECKING:
    from pathlib import Path

    from ynab_unlinked.context_object import YnabUnlinkedContext
    from ynab_unlinked.models import Transaction


XLSX_ROW_TO_READ = ["", "Fecha", "Tarjeta", "Concepto", "Importe", "Divisa", ""]
VALID_TYPES = [InputType.PDF, InputType.XLSX]


class BBVA(Entity):
    def parse(self, input_file: Path, context: YnabUnlinkedContext) -> list[Transaction]:
        import datetime as dt

        from ynab_unlinked.models import Transaction
        from ynab_unlinked.parsers import pdf, xls
        from ynab_unlinked.utils import extract_type

        input_type = extract_type(input_file, valid=VALID_TYPES)
        match input_type:
            case InputType.XLSX | InputType.XLS:
                generator = xls(input_file, read_after_row_like=XLSX_ROW_TO_READ)
                field_reader = self.__extract_fields_from_xlsx_row
            case _:
                # extract_type already rejected every type other than the valid ones
                generator = pdf(input_file, allow_empty_columns=False, expected_number_of_columns=3)
                field_reader = self.__extract_fields_from_pdf_row

        transactions = []

        for row in generator:
            date, payee, amount = field_reader(cast(list[str], row))

            # It can be that the row does not represent a transaction. Skip it
            try:
                parsed_date = dt.datetime.strptime(date, "%d/%m/%Y").date()
            except ValueError:
                continue

            transactions.append(
                Transaction(
                    date=parsed_date,
                    payee=payee,
                    amount=self.__parse_amount(amount),
                )
            )

        return transactions

    def __parse_amount(self, raw: str) -> float:
        # The pdf writes amounts in the Spanish format, "-1.234,56 €", with "." as thousands
        # separator. The xlsx carries the number itself, already with a "." as decimal point
        cleaned = raw.replace("€", "").strip()
        if "," in cleaned:
            cleaned = cleaned.replace(".", "").replace(",", ".")
        return float(cleaned)

    def __extract_fields_from_pdf_row(self, row: list[str]) -> tuple[str, ...]:
        # PDFs should have three columns
        # - Date with 2 lines for the date the transaction took place and when it was approved
        # - Concept, used for payee. Sometimes 2 lines including spending category
        # - Amount
        # A blank cell has no lines at all. It stays empty so the row is skipped as the
        # non transaction it is, the way the totals row is
        date = row[0].splitlines()[0] if row[0] else ""
        payee = row[1].splitlines()[0] if row[1] else ""
        amount = row[2]

        return date, payee, amount

    def __extract_fields_from_xlsx_row(self, row: list[str]) -> tuple[str, ...]:
        # XLSX fields are present from 1 to 4 for date, card number, payee and amount
        return str(row[1]), str(row[3]), str(row[4])

    def name(self) -> str:
        return "BBVA Credit Card"
