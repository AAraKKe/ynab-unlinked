"""Settings › Connection: the token (reveal, change after checking it) and the budget."""

from __future__ import annotations

from typing import TYPE_CHECKING

from nicegui import ui

from ynab_unlinked import keychain
from ynab_unlinked.config import LatestConfig
from ynab_unlinked.config import switch_budget as switch_budget_in
from ynab_unlinked.web import shell
from ynab_unlinked.web.components import (
    budget_tiles,
    button,
    dialog_box,
    loading,
    show_state,
    token_hint,
)
from ynab_unlinked.web.state import state
from ynab_unlinked.web.views.settings.common import current_config, kv
from ynab_unlinked.web.wording import ynab_error_message
from ynab_unlinked.web.ynab import fetch_budgets, load_budget

if TYPE_CHECKING:
    from ynab_unlinked.web.views.settings import Settings


def render(page: Settings) -> None:
    config, _ = state().require()
    revealed = {"on": False}

    with ui.element("div").classes("yul-kv"):
        kv("Token")
        with ui.element("div"):
            with ui.element("div").classes("yul-row"):
                token_label = ui.label(keychain.mask_token(config.api_key)).classes("yul-mono")
                token_label.mark("token-value")

                def reveal() -> None:
                    revealed["on"] = not revealed["on"]
                    token_label.set_text(
                        config.api_key if revealed["on"] else keychain.mask_token(config.api_key)
                    )
                    reveal_button.clear()
                    with reveal_button:
                        ui.label("Hide" if revealed["on"] else "Reveal")

                reveal_button = button("Reveal", kind="ghost", small=True, on_click=reveal)
                reveal_button.mark("reveal-token")
                button(
                    "Change", small=True, on_click=lambda: change_area.set_visibility(True)
                ).mark("change-token")
            with ui.element("div").style("margin-top:8px") as change_area:
                _token_change(page, change_area)
            change_area.set_visibility(False)

        kv("Budget")
        with ui.element("div").classes("yul-row"):
            ui.label(config.budget.name)
            button("Change", small=True, on_click=budget_dialog).mark("change-budget")

        kv("Config")
        ui.label(f"{config.version_number} · {LatestConfig.path()}").classes("yul-mono").style(
            "word-break:break-all"
        )


def _token_change(page: Settings, area: ui.element) -> None:
    with ui.element("div").classes("yul-row").style("align-items:flex-start"):
        new_token = (
            ui.input(placeholder="New Personal Access Token", password=True)
            .props("outlined dense")
            .classes("yul-grow")
            .mark("new-token")
        )
        save_button = button("Check and save", kind="primary", small=True)
        save_button.mark("save-token")
        button("Cancel", kind="ghost", small=True, on_click=lambda: area.set_visibility(False))
    with ui.element("div").classes("yul-faint yul-small"):
        token_hint()
    status = ui.element("div").classes("yul-row yul-inline-state")

    async def check_and_save() -> None:
        token = (new_token.value or "").strip()
        if not token:
            show_state(status, "error", "Paste the new token first.")
            return
        show_state(status, "loading", "Checking with YNAB…")
        save_button.disable()
        try:
            budgets = await fetch_budgets(token)
        except Exception as error:
            show_state(status, "error", ynab_error_message(error))
            return
        finally:
            save_button.enable()

        budget = current_config().budget
        if all(str(summary.id) != budget.id for summary in budgets):
            show_state(
                status,
                "error",
                f"This token cannot see the budget {budget.name!r}. "
                "Use a token of the same YNAB account.",
            )
            return

        def set_token(config: LatestConfig) -> None:
            config.api_key = token

        if await shell.save_config(set_token, "Token updated"):
            await page.rerender()

    save_button.on("click", check_and_save)


async def budget_dialog() -> None:
    config, _ = state().require()
    box = dialog_box(
        "Change budget",
        lede="Account settings, bank mappings and debt mappings belong to a budget, so "
        "switching clears them.",
    )
    dialog, body = box.dialog, box.body
    with body, ui.element("div").classes("yul-row yul-inline-state"):
        loading("Asking YNAB for your budgets…")
    with box.actions:
        button("Cancel", kind="ghost", on_click=dialog.close)
    dialog.open()

    try:
        budgets = await fetch_budgets(config.api_key)
    except Exception as error:
        show_state(body, "error", ynab_error_message(error))
        return

    body.clear()
    with body:
        grid, _ = budget_tiles(
            budgets,
            config.budget.id,
            lambda budget: switch_budget(dialog, str(budget.id), budget.name),
        )
        grid.style("margin-bottom:14px")


async def switch_budget(dialog: ui.dialog, budget_id: str, name: str) -> None:
    config, client = state().require()
    if budget_id == config.budget.id:
        dialog.close()
        return
    if not await shell.confirm(
        f"Switch to {name}?",
        [
            "Account settings, bank mappings and debt mappings are cleared",
            "The local copy of the old budget stays until you resync or reset",
            "Nothing changes in YNAB",
        ],
        "Switch budget",
    ):
        return
    try:
        budget = await load_budget(client, budget_id)
    except Exception as error:
        shell.notify(ynab_error_message(error), "error")
        return

    if not await shell.save_config(
        lambda config: switch_budget_in(config, budget), f"Budget switched to {budget.name}"
    ):
        return
    dialog.close()
    state().sync_in_background()
    ui.navigate.reload()
