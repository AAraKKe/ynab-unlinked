"""Net worth, debt netting and balance adjustments."""

from __future__ import annotations

import datetime as dt
import logging
import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from decimal import ROUND_HALF_UP, Decimal

from ynab import TransactionClearedStatus

from ynab_unlinked.buckets import Bucket
from ynab_unlinked.ynab_api.client import Client

logger = logging.getLogger(__name__)

_SEPARATORS = (".", ",")
_CURRENCY = r"[^\s\d.,+\-]+"
_AMOUNT = re.compile(
    rf"(?P<sign_before>[+-]*)\s*(?P<prefix>{_CURRENCY})?\s*(?P<sign_after>[+-]*)\s*"
    r"(?:(?P<whole>\d{1,3}(?:,\d{3})+|\d+)(?:\.(?P<fraction>\d*))?|\.(?P<bare_fraction>\d+))"
    rf"\s*(?P<suffix>{_CURRENCY})?"
)


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

    Strict, because the result is written to YNAB without a dialog in between: a currency
    symbol or a three letter ISO code may come before or after the number and a run of one
    sign (`-`, `+`) before it, nothing else. Group separators are only accepted between
    groups of three digits, so `12,34` in a `.` decimal budget is rejected rather than read
    as 1,234. Extra decimals are rounded to three. Returns None for anything else.

    Pass the budget's separators to read amounts the way the budget writes them: with
    `decimal_separator=","` and `group_separator="."`, `1.000,50` is 1000500. Any group
    separator works (a space, an apostrophe) as long as it sits between digits.
    """
    if decimal_separator not in _SEPARATORS:
        raise ValueError(f"Unsupported decimal separator {decimal_separator!r}")
    if group_separator == decimal_separator:
        raise ValueError("The decimal and group separators must differ")

    normalised = _normalise(text, decimal_separator, group_separator)
    if normalised is None or (match := _AMOUNT.fullmatch(normalised)) is None:
        logger.warning("Could not parse currency value: %s", text)
        return None

    signs = match["sign_before"] + match["sign_after"]
    currencies = [c for c in (match["prefix"], match["suffix"]) if c]
    if len(set(signs)) > 1 or len(currencies) > 1 or not all(map(_is_currency, currencies)):
        logger.warning("Could not parse currency value: %s", text)
        return None

    whole = (match["whole"] or "0").replace(",", "")
    fraction = match["fraction"] or match["bare_fraction"] or "0"
    value = Decimal(f"{whole}.{fraction}") * 1000
    milliunits = int(value.quantize(Decimal(1), rounding=ROUND_HALF_UP))
    return -milliunits if signs.startswith("-") else milliunits


def _normalise(text: str, decimal_separator: str, group_separator: str) -> str | None:
    """`text` with the `.` decimal and `,` group separators `_AMOUNT` reads.

    A group separator only counts between two digits, so a space separator does not eat the
    space before the currency. None when a `.` or `,` is left that is neither: `1.5` in a
    budget with `,` decimals.
    """
    placeholder = "\0"
    if group_separator:
        between_digits = rf"(?<=\d){re.escape(group_separator)}(?=\d)"
        text = re.sub(between_digits, placeholder, text)

    if any(separator in text for separator in _SEPARATORS if separator != decimal_separator):
        return None
    return text.replace(decimal_separator, ".").replace(placeholder, ",").strip()


def _is_currency(token: str) -> bool:
    """A three letter ISO code (`EUR`) or a currency symbol, maybe after letters (`€`, `US$`)."""
    # Upper case like ISO 4217 writes them, so that `12abc` is not taken for an amount
    if len(token) == 3 and token.isascii() and token.isalpha() and token.isupper():
        return True

    split = len(token)
    while split and unicodedata.category(token[split - 1]) == "Sc":
        split -= 1
    letters, symbol = token[:split], token[split:]
    return (
        bool(symbol)
        and len(letters) <= 2
        and (not letters or letters.isascii() and letters.isalpha())
    )
