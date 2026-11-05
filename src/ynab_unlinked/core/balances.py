"""Net worth, debt netting and balance adjustments."""

from __future__ import annotations

import datetime as dt
import logging
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace

from ynab import TransactionClearedStatus

from ynab_unlinked.buckets import Bucket
from ynab_unlinked.ynab_api.client import Client

logger = logging.getLogger(__name__)

_LEADING_PM_SIGNS = re.compile(r"([+\-\s]*)(.*)")
_INVALID_AMOUNT_CHARS = re.compile(r"[^\d\.,+\-]")
_SEPARATORS = (".", ",")


@dataclass(frozen=True)
class AccountBalance:
    id: str
    name: str
    bucket: Bucket
    balance: int  # milliunits


@dataclass(frozen=True)
class DebtNetting:
    """Spread the balance of a debt account over the accounts it is paid from."""

    debt_account_id: str
    mapped_to: tuple[str, ...]


@dataclass(frozen=True)
class NetWorth:
    accounts: tuple[AccountBalance, ...]
    """Balances after netting. Debt accounts keep their raw balance."""
    total: int
    """Cash, savings and assets after netting. Debt is already inside those balances."""

    def by_bucket(self) -> dict[Bucket, int]:
        totals = dict.fromkeys(Bucket, 0)
        for account in self.accounts:
            totals[account.bucket] += account.balance
        return totals

    def share(self, account_id: str) -> float:
        """Fraction of the total held by an account. Debt accounts hold no share."""
        account = next((a for a in self.accounts if a.id == account_id), None)
        if account is None:
            raise KeyError(f"Unknown account {account_id!r}")
        if account.bucket is Bucket.DEBT or self.total == 0:
            return 0.0
        return account.balance / self.total


def _even_split(balance: int, parts: int) -> int:
    # Truncates toward zero, as int(balance / parts) would. Floor division would hand a
    # different remainder to the first account for negative (debt) balances.
    share = abs(balance) // parts
    return -share if balance < 0 else share


def net_worth(accounts: Sequence[AccountBalance], nettings: Sequence[DebtNetting]) -> NetWorth:
    """
    Compute the net worth, subtracting each debt from the accounts it is mapped to.

    A debt balance is split evenly over its mapped accounts and the remainder lands on the
    first one. A debt with no mapping is not subtracted at all.
    """
    mapping = {netting.debt_account_id: netting.mapped_to for netting in reversed(nettings)}
    netted = {a.id: a.balance for a in accounts if a.bucket is not Bucket.DEBT}

    for debt in accounts:
        if debt.bucket is not Bucket.DEBT:
            continue
        targets = mapping.get(debt.id, ())
        if not targets:
            continue

        share = _even_split(debt.balance, len(targets))
        remainder = debt.balance - share * len(targets)
        for position, target in enumerate(targets):
            if target in netted:
                netted[target] += share + remainder if position == 0 else share

    result = tuple(
        account if account.bucket is Bucket.DEBT else replace(account, balance=netted[account.id])
        for account in accounts
    )
    total = sum(a.balance for a in result if a.bucket is not Bucket.DEBT)
    return NetWorth(accounts=result, total=total)


@dataclass(frozen=True)
class Adjustment:
    account_id: str
    old_balance: int
    new_balance: int

    @property
    def amount(self) -> int:
        """The transaction that takes the account from its old balance to the new one."""
        return self.new_balance - self.old_balance


def build_adjustments(current: Mapping[str, int], wanted: Mapping[str, int]) -> list[Adjustment]:
    """One adjustment per wanted balance that differs from the current one, in `wanted` order."""
    adjustments: list[Adjustment] = []
    for account_id, new_balance in wanted.items():
        if account_id not in current:
            raise KeyError(f"No current balance for account {account_id!r}")
        if (old_balance := current[account_id]) != new_balance:
            adjustments.append(
                Adjustment(account_id=account_id, old_balance=old_balance, new_balance=new_balance)
            )
    return adjustments


def create_adjustments(
    client: Client,
    budget_id: str,
    adjustments: Sequence[Adjustment],
    memo: str,
    payee: str,
    cleared: TransactionClearedStatus,
    date: dt.date,
) -> int:
    """Create one approved transaction per adjustment and return how many YNAB created."""
    return client.create_adjustments(
        budget_id,
        adjustments,
        memo=memo,
        payee=payee,
        cleared=cleared,
        date=date,
    )


def parse_amount_to_milliunits(
    text: str, *, decimal_separator: str = ".", group_separator: str = ","
) -> int | None:
    """
    Parse what a user typed as a balance (`123.45`, `-50`, `$1,000.00`) into milliunits.

    Lenient on purpose: anything that is not a digit, `.`, `,`, `+` or `-` is dropped (so a
    currency symbol or ISO code before or after the number is fine), the group separator is
    ignored, extra decimals are rounded to three and mixing `+` and `-` is rejected. Returns
    None when the text holds no number.

    Pass the budget's separators to read amounts the way the budget writes them: with
    `decimal_separator=","` and `group_separator="."`, `1.000,50` is 1000500. A group
    separator other than `.` or `,` (a space, an apostrophe) is dropped like any symbol.
    """
    if decimal_separator not in _SEPARATORS:
        raise ValueError(f"Unsupported decimal separator {decimal_separator!r}")
    if group_separator == decimal_separator:
        raise ValueError("The decimal and group separators must differ")

    # Rewrite the budget's separators into the `.` decimal and `,` group the parsing below
    # expects. A single table, so swapping `.` and `,` happens in one pass.
    roles = {decimal_separator: "."}
    if group_separator in _SEPARATORS:
        roles[group_separator] = ","

    cleaned = _cleanup_amount(text.translate(str.maketrans(roles)))
    if not cleaned:
        logger.warning("Could not parse currency value: %s", text)
        return None

    try:
        value = _to_float(_keep_one_leading_sign(cleaned))
    except ValueError as e:
        logger.warning("Could not parse currency value: %s (Reason: %s)", text, e)
        return None

    return int(f"{value:.3f}".replace(".", ""))


def _cleanup_amount(value: str) -> str:
    cleaned = _INVALID_AMOUNT_CHARS.sub("", value)
    if cleaned.startswith("."):
        cleaned = cleaned.lstrip(".").lstrip(",")
        cleaned = f"0.{cleaned}"
    return cleaned.strip(".,+")


def _keep_one_leading_sign(value: str) -> str:
    """Collapse the leading run of signs into a single `-` when the run starts with one."""
    signs = Counter(value)
    if signs.get("+", 0) > 0 and signs.get("-", 0) > 0:
        raise ValueError(f"The value {value} contains an unsupported set of +/- signs")

    match = _LEADING_PM_SIGNS.match(value.lstrip())
    assert match is not None  # both groups accept the empty string
    leading_signs, rest = match[1], match[2]
    sign = "-" if leading_signs.startswith("-") else ""
    return f"{sign}{rest}"


def _to_float(value: str) -> float:
    try:
        return float(value.replace(",", "_"))
    except ValueError:
        raise ValueError(f"Cannot convert the value {value} into a number") from None
