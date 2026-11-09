"""Settings › Net worth: which accounts pay each debt, the goal the plan follows, and how balance
adjustments are written."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from nicegui import run, ui

from ynab_unlinked.buckets import Bucket
from ynab_unlinked.config import ClearedStatus, DebtMapping, LatestConfig, TrackedAccount
from ynab_unlinked.web import accounts as tracking
from ynab_unlinked.web import shell
from ynab_unlinked.web.categories import balance_goals, goal_category, grouped
from ynab_unlinked.web.components import button
from ynab_unlinked.web.components.category_picker import category_picker
from ynab_unlinked.web.state import state
from ynab_unlinked.web.views.settings.common import kv, open_accounts

if TYPE_CHECKING:
    from ynab_unlinked.web.views.settings import Settings

CLEARED_LABELS = {
    ClearedStatus.CLEARED: "Cleared",
    ClearedStatus.UNCLEARED: "Uncleared",
    ClearedStatus.RECONCILED: "Reconciled",
}


async def render(page: Settings) -> None:
    config, _ = state().require()
    counted = tracking.effective_accounts(config, await open_accounts())
    ui.label(
        "Each debt is subtracted from the accounts that pay it, so cash shows what is really yours."
    ).classes("yul-muted").style("margin-bottom:10px")

    debts = [account for account in counted if account.bucket is Bucket.DEBT]
    payers = {account.id: account.name for account in counted if account.bucket is not Bucket.DEBT}
    mappings: dict[str, list[str]] = {}
    for debt in debts:
        mapping = config.debt_mapping(debt.id)
        mapped_to = mapping.mapped_to if mapping else []
        mappings[debt.id] = [target for target in mapped_to if target in payers]

    rows = ui.element("div")

    def draw() -> None:
        rows.clear()
        with rows:
            if not debts:
                ui.label("Count a credit card or a loan in Accounts to map it here.").classes(
                    "yul-faint"
                )
            for debt in debts:
                mapping_row(debt, payers, mappings[debt.id], draw)

    draw()

    await goal_section(page, config)

    ui.label("Balance adjustments").classes("yul-section").style("margin-top:18px")
    with ui.element("div").classes("yul-kv"):
        kv("Memo")
        memo = ui.input(value=config.adjustments.memo).props("outlined dense").mark("memo")
        kv("Payee")
        payee = ui.input(value=config.adjustments.payee).props("outlined dense").mark("payee")
        kv("Cleared status")
        cleared = (
            ui.select(
                {status.value: label for status, label in CLEARED_LABELS.items()},
                value=config.adjustments.cleared.value,
            )
            .props("outlined dense")
            .style("width:180px")
            .mark("cleared")
        )

    async def save_net_worth() -> None:
        payee_name = (payee.value or "").strip()
        if not payee_name:
            shell.notify("The adjustment payee cannot be empty", "warn")
            return
        new_memo = memo.value or ""
        new_cleared = ClearedStatus(cleared.value)

        def save(config: LatestConfig) -> None:
            # Mappings of debts not listed here (left out, closed) are kept as they are
            config.debt_mappings = [
                mapping
                for mapping in config.debt_mappings
                if mapping.debt_account_id not in mappings
            ] + [
                DebtMapping(debt_account_id=debt_id, mapped_to=list(targets))
                for debt_id, targets in mappings.items()
                if targets
            ]
            config.adjustments.memo = new_memo
            config.adjustments.payee = payee_name
            config.adjustments.cleared = new_cleared

        await shell.save_config(save, "Net worth settings saved")

    with ui.element("div").classes("yul-row").style("justify-content:flex-end;margin-top:12px"):
        button("Save net worth settings", kind="primary", on_click=save_net_worth).mark(
            "save-networth"
        )


async def goal_section(page: Settings, config: LatestConfig) -> None:
    """The category whose target the plan follows, picked among those with a balance target."""
    formatter = state().require_formatter()
    categories = await run.io_bound(state().store.categories, config.budget.id)
    if categories is None:  # the app is shutting down
        return
    ui.label("Goal").classes("yul-section").style("margin-top:18px")
    ui.label(
        "The target the plan follows. yul cannot see which goal YNAB shows on your phone, so "
        "pick it here among the categories with a balance target."
    ).classes("yul-muted").style("margin-bottom:10px")
    goals = balance_goals(categories)
    if not goals:
        ui.label(
            "No category has a balance target in YNAB. Add one there to follow it here."
        ).classes("yul-faint").mark("no-goal")
        return

    current = goal_category(categories, config.finances.goal_category_id)
    assert current is not None
    chosen = config.finances.goal_category_id == current.id

    async def pick(category_id: str | None) -> None:
        def change(config: LatestConfig) -> None:
            config.finances.goal_category_id = category_id

        name = next((c.name for c in goals if c.id == category_id), None)
        message = f"The plan follows {name}" if name else "The plan follows the largest target"
        if await shell.save_config(change, message):
            await page.rerender()

    with ui.element("div").classes("yul-row").style("flex-wrap:wrap;gap:8px").mark("goal"):
        target = formatter.format_amount_milli(current.goal_target or 0)
        with ui.element("span").classes("yul-pill acc").mark("goal-current"):
            ui.label(f"{current.name} · {target}")
        if not chosen:
            ui.label("the largest target").classes("yul-faint yul-small")
        category_picker(grouped(goals), pick, label="Change goal", marker="pick-goal")
        if chosen:
            button(
                "Use the largest target", kind="ghost", small=True, on_click=lambda: pick(None)
            ).mark("goal-default")


def mapping_row(
    debt: TrackedAccount,
    payers: dict[str, str],
    targets: list[str],
    redraw: Callable[[], None],
) -> None:
    with ui.element("div").classes("yul-map").mark(f"mapping-{debt.id}"):
        ui.label(debt.name).classes("name")
        ui.label("→").classes("ar")
        if not targets:
            ui.label("not netted").classes("yul-faint yul-small")
        for target in targets:
            with ui.element("span").classes("yul-pill acc"):
                ui.label(payers[target])
                remove = ui.label("×").style("cursor:pointer;opacity:.7")
                remove.mark(f"unmap-{debt.id}-{target}")

                def unmap(_: object, target: str = target) -> None:
                    targets.remove(target)
                    redraw()

                remove.on("click", unmap)
        choices = {key: name for key, name in payers.items() if key not in targets}
        if choices:
            add = (
                ui.select(choices, label="+ add account", value=None)
                .props("outlined dense")
                .style("min-width:180px")
                .mark(f"map-{debt.id}")
            )

            def mapped(e: object) -> None:
                value = getattr(e, "value", None)
                if value:
                    targets.append(value)
                    redraw()

            add.on_value_change(mapped)
