"""Net worth buckets shared by the config, the core services and the web app."""

from __future__ import annotations

from enum import StrEnum

from ynab import AccountType


class Bucket(StrEnum):
    CASH = "cash"
    SAVINGS = "savings"
    ASSETS = "assets"
    DEBT = "debt"


def bucket_for(account_type: AccountType) -> Bucket:
    """Default net worth bucket of a YNAB account type."""
    match account_type:
        case AccountType.CASH | AccountType.CHECKING:
            return Bucket.CASH
        case AccountType.SAVINGS:
            return Bucket.SAVINGS
        case (
            AccountType.CREDITCARD
            | AccountType.LINEOFCREDIT
            | AccountType.OTHERLIABILITY
            | AccountType.MORTGAGE
            | AccountType.AUTOLOAN
            | AccountType.STUDENTLOAN
            | AccountType.PERSONALLOAN
            | AccountType.MEDICALDEBT
            | AccountType.OTHERDEBT
        ):
            return Bucket.DEBT
        case AccountType.OTHERASSET:
            return Bucket.ASSETS
