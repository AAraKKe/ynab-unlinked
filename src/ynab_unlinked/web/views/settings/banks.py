"""Settings › Banks: a card per bank with its switch, and the dialog of its account and defaults."""

from __future__ import annotations

from typing import TYPE_CHECKING

from nicegui import ui

from ynab_unlinked.config import LatestConfig, LoaderConfig
from ynab_unlinked.entities.registry import AUTO, LoaderOption, LoaderSpec
from ynab_unlinked.web import shell
from ynab_unlinked.web.components import (
    bank_logo,
    button,
    card_switch,
    dialog_box,
    glass_card,
    run_dialog,
)
from ynab_unlinked.web.state import state
from ynab_unlinked.web.views.settings.common import current_config, open_accounts

if TYPE_CHECKING:
    from ynab_unlinked.web.views.settings import Settings


def bank_summary(spec: LoaderSpec, saved: LoaderConfig | None, accounts: dict[str, str]) -> str:
    """One line under the bank's name: its account and the defaults, or what is missing."""
    if saved is None:
        return "Pick the YNAB account its statements go to."
    parts = [f"→ {accounts.get(saved.account_id, saved.account_id)}"]
    parts += [
        f"{option.label.lower()}: {saved.options.get(option.key, option.default)}"
        for option in spec.options
    ]
    return " · ".join(parts)


async def render(page: Settings) -> None:
    config, _ = state().require()
    ui.label(
        "The banks yul reads statements from, the YNAB account each one goes to and the "
        "defaults every import starts with. All of it can be changed per file while importing."
    ).classes("yul-muted").style("margin-bottom:14px")
    accounts = await bank_accounts(config)
    with ui.element("div").classes("yul-bank-grid yul-stagger").mark("banks"):
        for spec in state().loaders:
            card = glass_card(hover=True).classes("yul-bank-card").mark(f"bank-{spec.key}")
            draw_bank(spec, card, accounts)


async def bank_accounts(config: LatestConfig) -> dict[str, str]:
    """Open accounts to choose from, plus any saved account that is no longer open."""
    accounts = {account.id: account.name for account in await open_accounts()}
    for loader_config in config.loaders.values():
        accounts.setdefault(loader_config.account_id, loader_config.account_id)
    return accounts


def draw_bank(spec: LoaderSpec, card: ui.element, accounts: dict[str, str]) -> None:
    """(Re)draw one bank's card from the config. Only this card changes after a save."""
    config, _ = state().require()
    saved = config.entity(spec.name)
    on = saved is not None and saved.enabled
    card.clear()
    with card:
        with ui.element("div").classes("yul-bank-head"):
            bank_logo(spec.key, spec.title, size=40)
            ui.element("span").classes("yul-grow")
            card_switch(
                card,
                on=on,
                marker=f"bank-toggle-{spec.key}",
                title="Read this bank's statements",
                on_change=lambda value: toggle_bank(spec, value, card, accounts),
            )
        ui.label(spec.title).classes("yul-bank-name")
        summary = ui.label(bank_summary(spec, saved, accounts)).classes("yul-bank-sum")
        summary.mark(f"bank-summary-{spec.key}")
        if saved is None:
            summary.classes("yul-warn")
        with ui.element("div").classes("yul-bank-foot"):
            ui.element("span").classes("yul-grow")
            button(
                "Settings",
                icon_name="settings",
                kind="ghost",
                small=True,
                on_click=lambda: bank_dialog(spec, card, accounts),
            ).mark(f"bank-settings-{spec.key}")


async def toggle_bank(
    spec: LoaderSpec, on: bool, card: ui.element, accounts: dict[str, str]
) -> None:
    saved = current_config().entity(spec.name)
    if saved is None:
        # Nothing to turn on yet: the dialog saves the account (and turns the bank on)
        if on:
            await bank_dialog(spec, card, accounts)
        else:
            draw_bank(spec, card, accounts)
        return
    if saved.enabled == on:
        return

    with shell.edit_config(f"{spec.title} turned {'on' if on else 'off'}") as config:
        if (loader := config.entity(spec.name)) is not None:
            loader.enabled = on
    draw_bank(spec, card, accounts)


async def bank_dialog(spec: LoaderSpec, card: ui.element, accounts: dict[str, str]) -> None:
    """Account and default options of one bank; saving turns a bank on the first time."""
    config, _ = state().require()
    saved = config.entity(spec.name)
    chosen: dict[str, str | None] = {spec.name: saved.account_id if saved else None}
    values = {
        option.key: saved.options.get(option.key, option.default) if saved else option.default
        for option in spec.options
    }
    box = dialog_box(classes="yul-bank-dialog")
    dialog = box.dialog
    with box.body:
        with ui.element("div").classes("yul-row").style("margin-bottom:14px"):
            bank_logo(spec.key, spec.title, size=36)
            with ui.element("div"):
                ui.label(spec.title).classes("yul-h2").style("margin:0")
                ui.label("Where its statements go and the defaults of every import").classes(
                    "yul-faint yul-small"
                )
        with ui.element("div").classes("yul-bank-form"):
            account = (
                ui.select(accounts, value=chosen[spec.name], clearable=True, label="YNAB account")
                .props("outlined dense")
                .mark(f"loader-{spec.key}")
            )
            account.on_value_change(lambda e: chosen.__setitem__(spec.name, e.value))
            for option in spec.options:
                option_control(spec, option, values)
        problem = ui.label().classes("yul-bad yul-small yul-inline-state")
    with box.actions:
        button("Cancel", kind="ghost", on_click=dialog.close)
        button("Save", kind="primary", on_click=lambda: save_bank()).mark(f"save-bank-{spec.key}")

    def save_bank() -> None:
        account_id = chosen[spec.name]
        if not account_id:
            problem.set_text("Pick the account its statements go to.")
            return
        non_default = {
            option.key: values[option.key]
            for option in spec.options
            if values[option.key] != option.default
        }

        with shell.edit_config(f"{spec.title} saved") as config:
            current = config.entity(spec.name)
            config.loaders[spec.name] = LoaderConfig(
                account_id=account_id,
                options=non_default,
                enabled=current.enabled if current else True,
            )
        dialog.submit(True)

    await run_dialog(dialog)
    if not card.is_deleted:
        draw_bank(spec, card, accounts)


def option_control(spec: LoaderSpec, option: LoaderOption, values: dict[str, str]) -> None:
    if option.choices:
        choices = list(option.choices)
        if AUTO not in choices and option.default == AUTO:
            choices.insert(0, AUTO)
        control = ui.select(choices, value=values[option.key], label=option.label)
    else:
        control = ui.input(label=option.label, value=values[option.key])
    control.props("outlined dense").style("min-width:160px").mark(f"option-{spec.key}-{option.key}")
    control.on_value_change(lambda e: values.__setitem__(option.key, str(e.value or AUTO)))
