from pathlib import Path
import re
import datetime as dt

from ynab_unlinked.models import Transaction
from ynab_unlinked.config import Config

from . import InputType

ANCHOR_LINE = "FECHA|CONCEPTO|LOCALIDAD|IMPORTE"
TRANSACTION_PATTER = re.compile(r"^(\d{2}/\d{2})\|([\w\s]+?)\|[\w\s]+?\|(.*EUR).*")


class SabadellParser:
    def parse(self, input_file: Path, config: Config) -> list[Transaction]:
        lines = input_file.read_text(encoding="cp1252").splitlines()
        start = False
        transactions: list[Transaction] = []
        for line in lines:
            if ANCHOR_LINE in line:
                start = True
                continue

            if not start:
                continue

            if groups := TRANSACTION_PATTER.match(line):
                parsed_date = self.__parse_date(groups[1])

                transactions.append(
                    Transaction(
                        date=parsed_date,
                        payee=self.__parse_payee(groups[2]),
                        amount=-self.__parse_amount(groups[3]),
                    )
                )
            else:
                start = False

        return transactions

    def __parse_date(self, raw: str) -> dt.date:
        current_year = dt.date.today().year
        return dt.datetime.strptime(f"{raw}/{current_year}", "%d/%m/%Y").date()

    def __parse_payee(self, raw: str) -> str:
        return raw.title()

    def __parse_amount(self, raw: str) -> float:
        return float(raw.replace("EUR", "").replace(",", "."))

    def supports_input_type(self, input_type: InputType) -> bool:
        """Only supports TXT for now"""
        return input_type is InputType.TXT
