"""Settings › Categories: how the finance views read income and spending, and the categories
whose outflows are not spending.

Adding or removing a category saves at once, like a card switch.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from nicegui import run, ui

from ynab_unlinked.config import LatestConfig
from ynab_unlinked.web import shell
from ynab_unlinked.web.categories import grouped
from ynab_unlinked.web.components.category_picker import category_picker
from ynab_unlinked.web.state import state
from ynab_unlinked.web.views.settings.common import current_config

if TYPE_CHECKING:
    from ynab_unlinked.web.views.settings import Settings

RULES = (
    (
        "Income",
        "Any money that comes into an account on your budget, whatever its category, unless it "
        "is a transfer between your accounts. Refunds and reimbursements are income too: they "
        "raise income and spending by the same amount.",
    ),
    (
        "Spending",
        "Any money that leaves an account on your budget, unless it is a transfer or its "
        "category is marked below.",
    ),
    (
        "Tracking accounts",
        "Money you move into a tracking account (investments, a pension) is a transfer, never "
        "spending. What the account does on its own is valuation.",
    ),
)


async def render(page: Settings) -> None:
    config = current_config()
    categories = await run.io_bound(state().store.categories, config.budget.id)

    with ui.element("div").classes("yul-catrules").mark("category-rules"):
        for title, text in RULES:
            with ui.element("div"):
                ui.label(title).classes("yul-catrules-t")
                ui.label(text).classes("yul-muted yul-small")

    ui.label("Not spending").classes("yul-section").style("margin-top:18px")
    ui.label(
        "Categories you use to set money aside or to move it to investments YNAB does not "
        "track. What leaves them still lowers net worth, but not as spending."
    ).classes("yul-muted").style("margin-bottom:10px")

    if not categories:
        ui.label("Your categories show up here after the next sync with YNAB.").classes(
            "yul-faint"
        ).mark("no-categories")
        return

    names = {category.id: category.name for category in categories}
    marked = [category_id for category_id in config.finances.not_spending if category_id in names]

    async def save(updated: list[str], message: str) -> None:
        def change(config: LatestConfig) -> None:
            # Ids no longer in the budget are kept: a sync may only be late
            kept = [c for c in config.finances.not_spending if c not in names]
            config.finances.not_spending = kept + updated

        if await shell.save_config(change, message):
            await page.rerender()

    async def add(category_id: str) -> None:
        if category_id not in marked:
            await save([*marked, category_id], f"{names[category_id]} is not spending now")

    async def remove(category_id: str) -> None:
        await save(
            [c for c in marked if c != category_id],
            f"{names[category_id]} counts as spending again",
        )

    with ui.element("div").classes("yul-row").style("flex-wrap:wrap;gap:8px").mark("not-spending"):
        if not marked:
            ui.label("None: every category's outflows are spending.").classes("yul-faint yul-small")
        for category_id in marked:
            with ui.element("span").classes("yul-pill acc").mark(f"not-spending-{category_id}"):
                ui.label(names[category_id])
                cross = ui.label("×").style("cursor:pointer;opacity:.7")
                cross.props["title"] = "Count it as spending again"
                cross.mark(f"spending-again-{category_id}")
                cross.on("click", lambda _, category_id=category_id: remove(category_id))
        available = [c for c in categories if c.id not in marked]
        category_picker(grouped(available), add, label="Add category", marker="add-not-spending")
