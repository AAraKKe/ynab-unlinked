"""The YNAB calls the views share: the budgets a token sees, one budget, account lists.

Blocking SDK calls run through `run.io_bound`; errors are raised as the SDK raises them and
worded by `wording.ynab_error_message`.
"""

from __future__ import annotations

from collections.abc import Iterable

from nicegui import run
from ynab import Account, PlanSummary

from ynab_unlinked.config import LatestConfig
from ynab_unlinked.config.models.v2 import Budget
from ynab_unlinked.store import StoredAccount
from ynab_unlinked.utils import budget_from_plan
from ynab_unlinked.ynab_api import Client


async def fetch_budgets(token: str) -> list[PlanSummary]:
    """The budgets a token can see, with their accounts. Raises what the SDK raises."""
    return await run.io_bound(Client(token).budgets, include_accounts=True) or []


async def load_budget(client: Client, budget_id: str) -> Budget:
    """The budget's settings (name, date and currency format) as the config stores them."""
    plan = await run.io_bound(client.budget, budget_id)
    if plan is None:
        raise ValueError(f"Could not find budget with ID {budget_id}")
    return budget_from_plan(plan)


def stored_accounts(accounts: Iterable[Account]) -> list[StoredAccount]:
    """YNAB's accounts as the store keeps them, deleted ones left out, by name."""
    return sorted(
        (
            StoredAccount(
                id=str(account.id),
                name=account.name,
                type=account.type.value,
                closed=account.closed,
                on_budget=account.on_budget,
                balance=account.balance,
                cleared_balance=account.cleared_balance,
                uncleared_balance=account.uncleared_balance,
            )
            for account in accounts
            if not account.deleted
        ),
        key=lambda account: account.name,
    )


def fallback_accounts(config: LatestConfig) -> list[StoredAccount]:
    """The accounts the config has settings for, open and at zero: when YNAB is out of reach."""
    return [
        StoredAccount(
            id=account.id,
            name=account.name,
            type=account.type,
            closed=False,
            on_budget=True,
            balance=0,
            cleared_balance=0,
            uncleared_balance=0,
        )
        for account in config.accounts
    ]


__all__ = ["fallback_accounts", "fetch_budgets", "load_budget", "stored_accounts"]
