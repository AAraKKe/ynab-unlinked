"""Settings: connection, banks, accounts, net worth and data.

Every save applies a change to the config on disk (`state().update_config`), which reloads the
app state, and toasts.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Awaitable, Callable

from nicegui import PageArguments, run, ui

from ynab_unlinked import keychain
from ynab_unlinked.buckets import Bucket
from ynab_unlinked.config import (
    ClearedStatus,
    DebtMapping,
    LatestConfig,
    LoaderConfig,
    TrackedAccount,
)
from ynab_unlinked.entities.registry import AUTO, LoaderOption, LoaderSpec
from ynab_unlinked.local_data import delete_local_data, local_data_paths
from ynab_unlinked.store import StoredAccount
from ynab_unlinked.utils import budget_from_plan
from ynab_unlinked.web import accounts as tracking
from ynab_unlinked.web import shell
from ynab_unlinked.web.components import bank_logo, button, glass_card, icon, pill, spinner
from ynab_unlinked.web.state import state
from ynab_unlinked.web.views.onboarding import (
    BUCKET_TITLES,
    budget_caption,
    fetch_budgets,
    ynab_error_message,
)

TABS = ("Connection", "Banks", "Accounts", "Net worth", "Data & privacy")
CLEARED_LABELS = {
    ClearedStatus.CLEARED: "Cleared",
    ClearedStatus.UNCLEARED: "Uncleared",
    ClearedStatus.RECONCILED: "Reconciled",
}
SERVER_DESCRIPTION = "On this computer only. Nothing is sent anywhere but YNAB."


def human_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    raise AssertionError("unreachable")


def _slug(tab: str) -> str:
    return tab.lower().replace(" & ", "-").replace(" ", "-")


def _config() -> LatestConfig:
    """The config as the app holds it, for reading. Changes go through `save`."""
    config, _ = state().require()
    return config


def save(change: Callable[[LatestConfig], None], message: str) -> None:
    """Apply `change` to the config on disk, keeping what another process saved, and toast."""
    state().update_config(change)
    shell.notify(message)


def _kv(key: str) -> None:
    ui.label(key).classes("k")


def token_location() -> str:
    if (name := keychain.backend_name()) is not None:
        return f"In your {name}, as the item “{keychain.SERVICE}”. Not in any file."
    return "In the settings file, in plain text: no keychain was found on this computer."


_SLUG_ALIASES = {"networth": "net-worth", "data": "data-privacy", "privacy": "data-privacy"}


def tab_from_slug(slug: str | None) -> str:
    """The tab a `?tab=` deep link names (`accounts`, `networth`, `privacy`, ...).

    Case insensitive; anything else opens Connection.
    """
    wanted = (slug or "").strip().lower()
    wanted = _SLUG_ALIASES.get(wanted, wanted)
    return next((tab for tab in TABS if _slug(tab) == wanted), TABS[0])


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


BUCKET_SWATCHES = {
    Bucket.CASH: "var(--series-3)",
    Bucket.SAVINGS: "var(--series-2)",
    Bucket.ASSETS: "var(--series-1)",
    Bucket.DEBT: "var(--text-3)",
}
"""The colours Net worth gives each bucket; debt has no series colour."""
BY_HAND_HINT = (
    "You enter this balance yourself. yul reminds you when it is older than 30 days and "
    "shows the pencil first in Net worth."
)


class AccountCards:
    """The Accounts tab: a card per open account, in the section of its bucket.

    Every open account counts in net worth unless its switch is off. Every change is saved at
    once; the config keeps an entry only for an account whose settings differ from its
    defaults, and leaves the entries of accounts that are not on a card alone.
    """

    def __init__(
        self, rows: dict[str, TrackedAccount], defaults: dict[str, TrackedAccount]
    ) -> None:
        self.rows = rows
        self.defaults = defaults
        """What each account would be without a config entry (`accounts.default_account`)."""
        self.root = ui.element("div").mark("accounts")
        self.first = True

    def draw(self) -> None:
        """(Re)draw every section. Only a bucket change moves cards, so only it redraws all."""
        self.root.clear()
        with self.root:
            for bucket, title in BUCKET_TITLES.items():
                ids = [i for i, row in self.rows.items() if row.bucket is bucket]
                if not ids:
                    continue
                with ui.element("div").classes("yul-section"):
                    ui.element("span").classes("yul-swatch").style(
                        f"background:{BUCKET_SWATCHES[bucket]}"
                    )
                    ui.label(title)
                grid = ui.element("div").classes("yul-acc-grid").mark(f"bucket-section-{bucket}")
                if self.first:
                    grid.classes("yul-stagger")
                with grid:
                    for account_id in ids:
                        card = (
                            glass_card().classes("yul-acc-card").mark(f"account-card-{account_id}")
                        )
                        self.draw_card(account_id, card)
        self.first = False

    def draw_card(self, account_id: str, card: ui.element) -> None:
        row = self.rows[account_id]
        on = row.counted
        card.clear()
        card.classes(add="live" if on else "off", remove="off" if on else "live")
        with card:
            with ui.element("div").classes("yul-acc-head"):
                name = ui.label(row.name).classes("yul-acc-name yul-grow")
                name.props["title"] = row.name
                switch = ui.switch(value=on).props("dense").mark(f"account-{account_id}")
                switch.props["title"] = "Counted in net worth"
                switch.props["aria-label"] = f"Count {row.name} in net worth"
            with ui.element("div").classes("yul-acc-buckets").mark(f"bucket-{account_id}"):
                for bucket, title in BUCKET_TITLES.items():
                    choice = pill(title, "acc" if bucket is row.bucket else "default")
                    choice.classes("click").mark(f"bucket-{account_id}-{bucket}")
                    choice.on("click", lambda _, bucket=bucket: self.set_bucket(account_id, bucket))
            with ui.element("div").classes("yul-acc-foot"):
                hand = ui.element("div").classes("yul-hand").mark(f"by-hand-{account_id}")
                if row.track_balance:
                    hand.classes("on")
                hand.props["title"] = BY_HAND_HINT
                hand.props["role"] = "switch"
                hand.props["aria-checked"] = "true" if row.track_balance else "false"
                with hand:
                    icon("pencil", 15)
                    ui.label("balance by hand")
                hand.on("click", lambda: self.set_by_hand(account_id, card))
        switch.on_value_change(lambda e: self.set_counted(account_id, bool(e.value), card))

    def set_counted(self, account_id: str, on: bool, card: ui.element) -> None:
        row = self.rows[account_id]
        if row.counted == on:
            return
        row.counted = on
        self.save("Counted in net worth" if on else "Left out of net worth")
        self.draw_card(account_id, card)

    def set_bucket(self, account_id: str, bucket: Bucket) -> None:
        row = self.rows[account_id]
        if row.bucket is bucket:
            return
        row.bucket = bucket
        self.save()
        self.draw()

    def set_by_hand(self, account_id: str, card: ui.element) -> None:
        row = self.rows[account_id]
        row.track_balance = not row.track_balance
        self.save()
        self.draw_card(account_id, card)

    def save(self, message: str = "Accounts saved") -> None:
        """Write the rows that differ from their defaults, keeping every other entry."""
        rows = [
            row.model_copy()
            for account_id, row in self.rows.items()
            if row != self.defaults[account_id]
        ]

        def change(config: LatestConfig) -> None:
            kept = [account for account in config.accounts if account.id not in self.rows]
            config.accounts = kept + rows

        save(change, message)


class Settings:
    def __init__(self, tab: str = TABS[0]) -> None:
        self.tab = tab
        self.tab_buttons: dict[str, ui.element] = {}
        self.panel: ui.element | None = None

    async def render(self) -> None:
        with ui.element("div").classes("yul-tabs"):
            for tab in TABS:
                item = ui.label(tab).classes("yul-tab").mark(f"tab-{_slug(tab)}")
                item.on("click", lambda _, tab=tab: self.select(tab))
                self.tab_buttons[tab] = item
        self.panel = glass_card().mark("settings-panel")
        await self.select(self.tab)

    async def select(self, tab: str) -> None:
        self.tab = tab
        for name, item in self.tab_buttons.items():
            if name == tab:
                item.classes(add="on")
            else:
                item.classes(remove="on")
        renderers: dict[str, Callable[[], Awaitable[None] | None]] = {
            "Connection": self.connection,
            "Banks": self.loaders,
            "Accounts": self.accounts,
            "Net worth": self.net_worth,
            "Data & privacy": self.data,
        }
        assert self.panel is not None
        self.panel.clear()
        with self.panel:
            result = renderers[tab]()
            if result is not None:
                await result

    async def rerender(self) -> None:
        await self.select(self.tab)

    async def open_accounts(self) -> list[StoredAccount]:
        """The budget's open accounts, or the configured ones when YNAB cannot be reached."""
        try:
            accounts = await state().budget_accounts()
        except Exception as error:
            shell.notify(ynab_error_message(error), "warn")
            config, _ = state().require()
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
        return [account for account in accounts if not account.closed]

    # ---- Connection ----------------------------------------------------------------------

    def connection(self) -> None:
        config, _ = state().require()
        revealed = {"on": False}

        with ui.element("div").classes("yul-kv"):
            _kv("Token")
            with ui.element("div"):
                with ui.element("div").classes("yul-row"):
                    token_label = ui.label(keychain.mask_token(config.api_key)).classes("yul-mono")
                    token_label.mark("token-value")

                    def reveal() -> None:
                        revealed["on"] = not revealed["on"]
                        token_label.set_text(
                            config.api_key
                            if revealed["on"]
                            else keychain.mask_token(config.api_key)
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
                    self.token_change(change_area)
                change_area.set_visibility(False)

            _kv("Budget")
            with ui.element("div").classes("yul-row"):
                ui.label(config.budget.name)
                button("Change", small=True, on_click=self.budget_dialog).mark("change-budget")

            _kv("Config")
            ui.label(f"{config.version_number} · {LatestConfig.path()}").classes("yul-mono").style(
                "word-break:break-all"
            )

    def token_change(self, area: ui.element) -> None:
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
        status = ui.element("div").classes("yul-row yul-inline-state")

        async def check_and_save() -> None:
            token = (new_token.value or "").strip()
            status.clear()
            if not token:
                with status:
                    ui.label("Paste the new token first.").classes("yul-bad")
                return
            with status:
                spinner()
                ui.label("Checking with YNAB…").classes("yul-muted")
            save_button.disable()
            try:
                budgets = await fetch_budgets(token)
            except Exception as error:
                status.clear()
                with status:
                    ui.label(ynab_error_message(error)).classes("yul-bad")
                return
            finally:
                save_button.enable()

            config = _config()
            if all(str(budget.id) != config.budget.id for budget in budgets):
                status.clear()
                with status:
                    ui.label(
                        f"This token cannot see the budget {config.budget.name!r}. "
                        "Use a token of the same YNAB account."
                    ).classes("yul-bad")
                return

            def change(config: LatestConfig) -> None:
                config.api_key = token

            save(change, "Token updated")
            await self.rerender()

        save_button.on("click", check_and_save)

    async def budget_dialog(self) -> None:
        config, _ = state().require()
        with ui.dialog() as dialog, ui.element("div").classes("yul-card yul-dialog"):
            ui.label("Change budget").classes("yul-h2")
            ui.label(
                "Account settings, bank mappings and debt mappings belong to a budget, so "
                "switching clears them."
            ).classes("yul-lede")
            body = ui.element("div")
            with body, ui.element("div").classes("yul-row yul-inline-state"):
                spinner()
                ui.label("Asking YNAB for your budgets…").classes("yul-muted")
            with ui.element("div").classes("yul-row").style("justify-content:flex-end"):
                button("Cancel", kind="ghost", on_click=dialog.close)
        dialog.open()

        try:
            budgets = await fetch_budgets(config.api_key)
        except Exception as error:
            body.clear()
            with body:
                ui.label(ynab_error_message(error)).classes("yul-bad")
            return

        body.clear()
        with body, ui.element("div").classes("yul-optgrid").style("margin-bottom:14px"):
            for budget in budgets:
                with ui.element("div").classes("yul-opt").mark(f"budget-{budget.id}") as option:
                    ui.label(budget.name)
                    ui.label(budget_caption(budget)).classes("yul-faint yul-small")
                if str(budget.id) == config.budget.id:
                    option.classes(add="on")
                option.on(
                    "click",
                    lambda _, budget_id=str(budget.id), name=budget.name: self.switch_budget(
                        dialog, budget_id, name
                    ),
                )

    async def switch_budget(self, dialog: ui.dialog, budget_id: str, name: str) -> None:
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
            plan = await run.io_bound(client.budget, budget_id)
            if plan is None:
                raise ValueError(f"Could not find budget with ID {budget_id}")
            budget = budget_from_plan(plan)
        except Exception as error:
            shell.notify(ynab_error_message(error), "error")
            return

        def change(config: LatestConfig) -> None:
            config.budget = budget
            config.loaders = {}
            config.accounts = []
            config.debt_mappings = []
            config.last_reconciliation_date = None

        save(change, f"Budget switched to {budget.name}")
        dialog.close()
        state().sync_in_background()
        ui.navigate.reload()

    # ---- Banks ---------------------------------------------------------------------------

    async def loaders(self) -> None:
        config, _ = state().require()
        ui.label(
            "The banks yul reads statements from, the YNAB account each one goes to and the "
            "defaults every import starts with. All of it can be changed per file while importing."
        ).classes("yul-muted").style("margin-bottom:14px")
        accounts = await self.bank_accounts(config)
        with ui.element("div").classes("yul-bank-grid yul-stagger").mark("banks"):
            for spec in state().loaders:
                card = glass_card(hover=True).classes("yul-bank-card").mark(f"bank-{spec.key}")
                self.draw_bank(spec, card, accounts)

    async def bank_accounts(self, config: LatestConfig) -> dict[str, str]:
        """Open accounts to choose from, plus any saved account that is no longer open."""
        accounts = {account.id: account.name for account in await self.open_accounts()}
        for loader_config in config.loaders.values():
            accounts.setdefault(loader_config.account_id, loader_config.account_id)
        return accounts

    def draw_bank(self, spec: LoaderSpec, card: ui.element, accounts: dict[str, str]) -> None:
        """(Re)draw one bank's card from the config. Only this card changes after a save."""
        config, _ = state().require()
        saved = config.entity(spec.name)
        on = saved is not None and saved.enabled
        card.clear()
        card.classes(add="live" if on else "off", remove="off" if on else "live")
        with card:
            with ui.element("div").classes("yul-bank-head"):
                bank_logo(spec.key, spec.title, size=40)
                ui.element("span").classes("yul-grow")
                switch = ui.switch(value=on).props("dense").mark(f"bank-toggle-{spec.key}")
                switch.props["title"] = "Read this bank's statements"
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
                    on_click=lambda: self.bank_dialog(spec, card, accounts),
                ).mark(f"bank-settings-{spec.key}")
        switch.on_value_change(lambda e: self.toggle_bank(spec, bool(e.value), card, accounts))

    async def toggle_bank(
        self, spec: LoaderSpec, on: bool, card: ui.element, accounts: dict[str, str]
    ) -> None:
        saved = _config().entity(spec.name)
        if saved is None:
            # Nothing to turn on yet: the dialog saves the account (and turns the bank on)
            if on:
                await self.bank_dialog(spec, card, accounts)
            else:
                self.draw_bank(spec, card, accounts)
            return
        if saved.enabled == on:
            return

        def change(config: LatestConfig) -> None:
            if (loader := config.entity(spec.name)) is not None:
                loader.enabled = on

        save(change, f"{spec.title} turned {'on' if on else 'off'}")
        self.draw_bank(spec, card, accounts)

    async def bank_dialog(
        self, spec: LoaderSpec, card: ui.element, accounts: dict[str, str]
    ) -> None:
        """Account and default options of one bank; saving turns a bank on the first time."""
        config, _ = state().require()
        saved = config.entity(spec.name)
        chosen: dict[str, str | None] = {spec.name: saved.account_id if saved else None}
        values = {
            option.key: saved.options.get(option.key, option.default) if saved else option.default
            for option in spec.options
        }
        with (
            ui.dialog() as dialog,
            ui.element("div").classes("yul-card yul-dialog yul-bank-dialog"),
        ):
            with ui.element("div").classes("yul-row").style("margin-bottom:14px"):
                bank_logo(spec.key, spec.title, size=36)
                with ui.element("div"):
                    ui.label(spec.title).classes("yul-h2").style("margin:0")
                    ui.label("Where its statements go and the defaults of every import").classes(
                        "yul-faint yul-small"
                    )
            with ui.element("div").classes("yul-bank-form"):
                account = (
                    ui.select(
                        accounts, value=chosen[spec.name], clearable=True, label="YNAB account"
                    )
                    .props("outlined dense")
                    .mark(f"loader-{spec.key}")
                )
                account.on_value_change(lambda e: chosen.__setitem__(spec.name, e.value))
                for option in spec.options:
                    self.option_control(spec, option, values)
            problem = ui.label().classes("yul-bad yul-small yul-inline-state")
            with ui.element("div").classes("yul-row").style("justify-content:flex-end"):
                button("Cancel", kind="ghost", on_click=dialog.close)
                button("Save", kind="primary", on_click=lambda: save_bank()).mark(
                    f"save-bank-{spec.key}"
                )

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

            def change(config: LatestConfig) -> None:
                current = config.entity(spec.name)
                config.loaders[spec.name] = LoaderConfig(
                    account_id=account_id,
                    options=non_default,
                    enabled=current.enabled if current else True,
                )

            save(change, f"{spec.title} saved")
            dialog.submit(True)

        dialog.open()
        try:
            await dialog
        finally:
            dialog.delete()
        if not card.is_deleted:
            self.draw_bank(spec, card, accounts)

    def option_control(
        self, spec: LoaderSpec, option: LoaderOption, values: dict[str, str]
    ) -> None:
        if option.choices:
            choices = list(option.choices)
            if AUTO not in choices and option.default == AUTO:
                choices.insert(0, AUTO)
            control = ui.select(choices, value=values[option.key], label=option.label)
        else:
            control = ui.input(label=option.label, value=values[option.key])
        control.props("outlined dense").style("min-width:160px").mark(
            f"option-{spec.key}-{option.key}"
        )
        control.on_value_change(lambda e: values.__setitem__(option.key, str(e.value or AUTO)))

    # ---- Accounts ------------------------------------------------------------------------

    async def accounts(self) -> None:
        config, _ = state().require()
        ui.label(
            "Every open account counts in your net worth. Switch one off to leave it out, "
            "pick the group it belongs to, and mark the ones whose balance you enter yourself. "
            "Changes are saved as you make them."
        ).classes("yul-muted").style("margin-bottom:14px").mark("accounts-lede")

        rows: dict[str, TrackedAccount] = {}
        defaults: dict[str, TrackedAccount] = {}
        for account in await self.open_accounts():
            defaults[account.id] = tracking.default_account(account)
            # The name and type come from the budget, the rest from the config
            rows[account.id] = tracking.account_settings(config, account).model_copy(
                update={"name": account.name, "type": account.type}
            )
        AccountCards(rows, defaults).draw()

    # ---- Net worth -----------------------------------------------------------------------

    async def net_worth(self) -> None:
        config, _ = state().require()
        counted = tracking.effective_accounts(config, await self.open_accounts())
        ui.label(
            "Each debt is subtracted from the accounts that pay it, so cash shows what is "
            "really yours."
        ).classes("yul-muted").style("margin-bottom:10px")

        debts = [account for account in counted if account.bucket is Bucket.DEBT]
        payers = {
            account.id: account.name for account in counted if account.bucket is not Bucket.DEBT
        }
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
                    self.mapping_row(debt, payers, mappings[debt.id], draw)

        draw()

        ui.label("Balance adjustments").classes("yul-section").style("margin-top:18px")
        with ui.element("div").classes("yul-kv"):
            _kv("Memo")
            memo = ui.input(value=config.adjustments.memo).props("outlined dense").mark("memo")
            _kv("Payee")
            payee = ui.input(value=config.adjustments.payee).props("outlined dense").mark("payee")
            _kv("Cleared status")
            cleared = (
                ui.select(
                    {status.value: label for status, label in CLEARED_LABELS.items()},
                    value=config.adjustments.cleared.value,
                )
                .props("outlined dense")
                .style("width:180px")
                .mark("cleared")
            )

        def save_net_worth() -> None:
            payee_name = (payee.value or "").strip()
            if not payee_name:
                shell.notify("The adjustment payee cannot be empty", "warn")
                return
            new_memo = memo.value or ""
            new_cleared = ClearedStatus(cleared.value)

            def change(config: LatestConfig) -> None:
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

            save(change, "Net worth settings saved")

        with ui.element("div").classes("yul-row").style("justify-content:flex-end;margin-top:12px"):
            button("Save net worth settings", kind="primary", on_click=save_net_worth).mark(
                "save-networth"
            )

    def mapping_row(
        self,
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

    # ---- Data & privacy ------------------------------------------------------------------

    def data(self) -> None:
        current = state()
        config, _ = current.require()
        path = current.store.path
        size = human_size(path.stat().st_size) if path.is_file() else "not created yet"
        with ui.element("div").classes("yul-kv"):
            _kv("Where it runs")
            ui.label(SERVER_DESCRIPTION)
            _kv("Budget copy")
            ui.label(
                f"{path} · {size} · {shell.sync_label(current.last_sync, dt.datetime.now(dt.UTC))}"
            ).classes("yul-mono").style("word-break:break-all").mark("store-info")
            _kv("Settings file")
            ui.label(str(LatestConfig.path())).classes("yul-mono").style("word-break:break-all")
            _kv("YNAB token")
            ui.label(token_location()).mark("token-location")
            _kv("What is kept")
            with ui.element("div").classes("yul-muted yul-small"):
                ui.label("The budget, banks, account settings and adjustment settings.")
                ui.label(
                    "A copy of the budget's transactions and accounts, and a log of what yul did."
                )
                ui.label("Nothing leaves this computer except calls to api.ynab.com.")

        with ui.element("div").classes("yul-row").style("margin-top:14px;gap:8px"):
            resync = button("Resync from scratch", small=True).mark("resync")
            button("Reset all data", kind="danger", small=True, on_click=self.reset).mark(
                "reset-data"
            )

        async def resync_now() -> None:
            resync.disable()
            try:
                state().store.clear(config.budget.id)
                result = await state().sync()
            except Exception as error:
                shell.notify(f"Sync failed: {error}", "error")
            else:
                if result is not None:
                    shell.notify(shell.sync_message(result))
            finally:
                resync.enable()
            await self.rerender()

        resync.on("click", resync_now)

    async def reset(self) -> None:
        paths = local_data_paths()
        lines = [f"Delete {path}" for path in paths]
        if (name := keychain.backend_name()) is not None:
            lines.append(f"Remove the token from your {name}")
        lines.append(
            "Your YNAB budget is not touched. Revoke the token in YNAB if you stop using yul."
        )
        if not await shell.confirm("Reset all data?", lines, "Delete everything", danger=True):
            return
        delete_local_data(paths)
        state().reload()
        ui.navigate.to(shell.ONBOARDING_PATH)


@shell.view(
    "/settings",
    key="settings",
    title="Settings",
    subtitle="Connection, banks, accounts, privacy",
    icon="settings",
    order=90,
    bottom=True,
    live=False,
)
async def settings_view(args: PageArguments) -> None:
    await Settings(tab_from_slug(args.query_parameters.get("tab"))).render()
