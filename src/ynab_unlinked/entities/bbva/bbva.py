from __future__ import annotations

from typing import TYPE_CHECKING, assert_never, cast

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

        from ynab_unlinked.exceptions import ParsingError
        from ynab_unlinked.models import Transaction
        from ynab_unlinked.parsers import pdf, xls
        from ynab_unlinked.utils import extract_type

        input_type = extract_type(input_file, valid=VALID_TYPES)
        match input_type:
            case InputType.XLSX | InputType.XLS:
                generator = xls(input_file, read_after_row_like=XLSX_ROW_TO_READ)
                field_reader = self.__extract_fields_from_xlsx_row
            case InputType.PDF:
                generator = pdf(input_file, allow_empty_columns=False, expected_number_of_columns=3)
                field_reader = self.__extract_fields_from_pdf_row
            case (InputType.TXT | InputType.CSV | InputType.HTML) as file_type:
                raise NotImplementedError(
                    f"BBVA does not support input file of type {file_type.value!r}"
                )
            case never:
                assert_never(never)

        transactions = []

        for row in generator:
            parsed_row = field_reader(cast(list[str], row))
            if parsed_row is None:
                raise ParsingError(
                    input_file,
                    "Malformed Transaction Table: Could not extract the date, payee and a mount for one row",
                )

            date, payee, amount = parsed_row

            # It can be that the row does not represent a transaction. Skip it
            try:
                parsed_date = dt.datetime.strptime(date, "%d/%m/%Y").date()
            except ValueError:
                continue

            transactions.append(
                Transaction(
                    date=parsed_date,
                    payee=payee,
                    amount=float(amount.replace("€", "").replace(",", ".")),
                )
            )

        return transactions

    def __extract_fields_from_pdf_row(self, row: list[str]) -> tuple[str, ...] | None:
        # PDFs should have three columns
        # - Date with 2 lines for the date the transaction took place and when it was approved
        # - Concept, used for payee. Sometimes 2 lines including spending category
        # - Amount
        if len(row) != 3:
            return None

        date = row[0].splitlines()[0]
        payee = row[1].splitlines()[0]
        amount = row[2]

        return date, payee, amount

    def __extract_fields_from_xlsx_row(self, row: list[str]) -> tuple[str, ...] | None:
        # XLSX fields are present from 1 to 4 for date, card number, payee and amount
        return str(row[1]), str(row[3]), str(row[4])

    def name(self) -> str:
        return "BBVA Credit Card"
