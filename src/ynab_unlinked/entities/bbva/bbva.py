import datetime as dt
from pathlib import Path
from typing import cast

from ynab_unlinked.context_object import YnabUnlinkedContext
from ynab_unlinked.entities import Entity
from ynab_unlinked.exceptions import ParsingError
from ynab_unlinked.models import Transaction
from ynab_unlinked.parsers import pdf


class BBVA(Entity):
    def parse(
        self, input_file: Path, context: YnabUnlinkedContext
    ) -> list[Transaction]:
        transactions = []

        for row in pdf(
            input_file, allow_empty_columns=False, expected_number_of_columns=3
        ):
            parsed_row = self.__extract_fields_from_row(cast(list[str], row))
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

    def __extract_fields_from_row(self, row: list[str]) -> tuple[str, ...] | None:
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

    def name(self) -> str:
        return "BBVA Credit Card"
