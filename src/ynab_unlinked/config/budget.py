"""The budget yul keeps in its config, read from what YNAB returns for it."""

from __future__ import annotations

from ynab import PlanDetail

from ynab_unlinked.config.models.v2 import Budget, CurrencyFormat


def budget_from_plan(budget_details: PlanDetail) -> Budget:
    """The `Budget` yul stores, built from the full budget YNAB returns."""
    if budget_details.currency_format is None:
        raise ValueError(f"Budget {budget_details.name!r} has no currency format")

    if budget_details.date_format is None:
        raise ValueError(f"Budget {budget_details.name!r} has no date format")

    return Budget(
        id=str(budget_details.id),
        name=budget_details.name,
        date_format=budget_details.date_format.format,
        currency_format=CurrencyFormat(
            iso_code=budget_details.currency_format.iso_code,
            decimal_digits=budget_details.currency_format.decimal_digits,
            decimal_separator=budget_details.currency_format.decimal_separator,
            symbol_first=budget_details.currency_format.symbol_first,
            group_separator=budget_details.currency_format.group_separator,
            currency_symbol=budget_details.currency_format.currency_symbol,
            display_symbol=budget_details.currency_format.display_symbol,
        ),
    )
