"""The onboarding wizard (`Wizard`) and its page. The steps and the account choices are in
`data`, the copy's progress line in `progress`."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field

from fastapi.responses import RedirectResponse
from nicegui import context, run, ui
from ynab import PlanSummary

from ynab_unlinked import keychain
from ynab_unlinked.config import LatestConfig, LoaderConfig
from ynab_unlinked.config.core import ConfigError
from ynab_unlinked.config.models.v2 import Budget
from ynab_unlinked.entities.registry import LoaderSpec
from ynab_unlinked.web import shell, theme
from ynab_unlinked.web.components import (
    bank_logo,
    budget_tiles,
    button,
    check,
    loading,
    pill,
    set_class,
    show_state,
    spinner,
)
from ynab_unlinked.web.state import state
from ynab_unlinked.web.views.onboarding.data import (
    BUDGET,
    DONE,
    LOADERS,
    STEPS,
    TOKEN,
    AccountOption,
    CopyState,
)
from ynab_unlinked.web.views.onboarding.progress import LineProgress
from ynab_unlinked.web.wording import (
    COPY_FAILED,
    COPY_NOTE,
    COPY_TITLE,
    SAVE_FAILED,
    copy_error_message,
    plural,
    ynab_error_message,
)
from ynab_unlinked.web.ynab import fetch_budgets, load_budget
from ynab_unlinked.ynab_api import Client

logger = logging.getLogger(__name__)


@dataclass
class Wizard:
    step: int = TOKEN
    token: str = ""
    checked_token: str | None = None
    budgets: list[PlanSummary] = field(default_factory=list[PlanSummary])
    budget_id: str | None = None
    budget: Budget | None = None
    accounts: list[AccountOption] = field(default_factory=list[AccountOption])
    loader_accounts: dict[str, str | None] = field(default_factory=dict[str, str | None])
    busy: bool = False
    message: str | None = None
    message_is_error: bool = False
    copy_state: CopyState = "running"
    copy_error: str | None = None

    rail: ui.element | None = None
    body: ui.element | None = None
    message_box: ui.element | None = None
    forward: ui.button | None = None
    budget_tiles: dict[str, ui.element] = field(default_factory=dict[str, ui.element])
    loaders_box: ui.element | None = None
    done_box: ui.element | None = None

    # ---- data ----------------------------------------------------------------------------

    def draft(self) -> LatestConfig:
        """The config the wizard would write right now. Every open account counts."""
        assert self.budget is not None and self.checked_token is not None
        account_ids = {account.id for account in self.accounts}
        return LatestConfig(
            api_key=self.checked_token,
            budget=self.budget,
            loaders={
                name: LoaderConfig(account_id=account_id)
                for name, account_id in self.loader_accounts.items()
                if account_id is not None and account_id in account_ids
            },
            accounts=[],
        )

    def guess_loader_account(self, spec: LoaderSpec) -> str | None:
        """Preselect the one account named after the bank, if there is exactly one."""
        needles = {spec.title.lower(), spec.key.lower()}
        matches = [
            account.id
            for account in self.accounts
            if any(needle in account.name.lower() for needle in needles)
        ]
        return matches[0] if len(matches) == 1 else None

    @property
    def accounts_loaded(self) -> bool:
        return self.budget is not None and self.budget.id == self.budget_id

    # ---- actions -------------------------------------------------------------------------

    def say(self, message: str | None, *, error: bool = False) -> None:
        self.message = message
        self.message_is_error = error
        self.show_message()

    async def check_token(self) -> bool:
        client = context.client
        token = self.token.strip()
        if not token:
            self.say("Paste your Personal Access Token first.", error=True)
            return False

        self.busy = True
        self.say(None)
        self.update_footer()
        try:
            budgets = await fetch_budgets(token)
        except Exception as error:
            self.checked_token = None
            self.say(ynab_error_message(error), error=True)
            return False
        finally:
            self.busy = False
            self.show_message()
            self.update_footer()

        self.checked_token = token
        self.budgets = budgets
        if (kept := state().token_lost) is not None and any(
            str(budget.id) == kept.budget.id for budget in budgets
        ):

            def set_token(config: LatestConfig) -> None:
                config.api_key = token

            # The same budget: the saved config only needs its token back, even if its file
            # is gone (the only save with a fallback). Not `shell.save_config`, which has none
            try:
                await run.io_bound(state().update_config, set_token, kept)
            except Exception:
                logger.exception("The token could not be saved")
                shell.notify(SAVE_FAILED, "error")
                return False
            with client:
                ui.navigate.to(shell.HOME_PATH)
            return True
        if len(budgets) == 1:
            self.budget_id = str(budgets[0].id)
        self.say(f"Token works · {plural(len(budgets), 'budget')} found")
        return True

    async def load_budget(self) -> None:
        """Read the picked budget and its accounts, then draw the banks in place."""
        assert self.checked_token is not None and self.budget_id is not None
        client = Client(self.checked_token)
        budget_id = self.budget_id
        self.busy = True
        self.message = None
        self.fill_loaders()
        self.update_footer()
        try:
            budget = await load_budget(client, budget_id)
            accounts = await run.io_bound(client.accounts, budget_id) or []
        except Exception as error:
            self.message, self.message_is_error = ynab_error_message(error), True
        else:
            self.budget = budget
            self.accounts = [
                AccountOption(id=str(account.id), name=account.name)
                for account in sorted(accounts, key=lambda a: a.name)
                if not account.closed and not account.deleted
            ]
            self.prepare_loaders()
        finally:
            self.busy = False
        self.fill_loaders()
        self.update_footer()

    def prepare_loaders(self) -> None:
        account_ids = {account.id for account in self.accounts}
        for spec in state().loaders:
            current = self.loader_accounts.get(spec.name)
            if current is None or current not in account_ids:
                self.loader_accounts[spec.name] = self.guess_loader_account(spec)

    async def finish(self) -> None:
        try:
            await run.io_bound(self.draft().save)
        except (OSError, ConfigError) as error:
            self.say(f"The settings could not be saved: {error}", error=True)
            return
        # Reading the new config opens the budget copy: off the event loop
        await run.io_bound(state().reload)
        self.step = DONE
        self.refresh()
        await self.first_copy()

    async def first_copy(self) -> None:
        """Copy the budget from YNAB in the foreground, the line following its progress."""
        self.copy_state, self.copy_error = "running", None
        line = self.fill_done()
        assert self.done_box is not None
        try:
            await state().sync(LineProgress(line, self.done_box.client))
        except Exception as error:
            self.copy_state, self.copy_error = "failed", copy_error_message(error)
        else:
            self.copy_state = "done"
        self.fill_done()

    async def advance(self) -> None:
        if self.busy:
            return
        match self.step:
            case 0:
                if self.checked_token != self.token.strip() and not await self.check_token():
                    return
            case 1:
                if self.budget_id is None:
                    self.say("Pick the budget yul should work with.", error=True)
                    return
                self.step = LOADERS
                self.message = None
                self.refresh()
                if not self.accounts_loaded:
                    await self.load_budget()
                return
            case 2:
                if self.accounts_loaded:
                    await self.finish()
                return
            case _:
                return
        self.step += 1
        self.message = None
        self.refresh()

    def back(self) -> None:
        if self.busy or self.step in (TOKEN, DONE):
            return
        self.step -= 1
        self.message = None
        self.refresh()

    # ---- rendering -----------------------------------------------------------------------

    def render(self) -> None:
        with ui.element("div").classes("yul-onb"), ui.element("div").classes("yul-card yul-wiz"):
            self.rail = ui.element("div").classes("yul-rail")
            self.body = ui.element("div").classes("yul-wiz-body")
        self.refresh()

    def refresh(self) -> None:
        """Draw the rail and the current step. Only for a change of step."""
        if self.rail is None or self.body is None:
            return
        self.rail.clear()
        with self.rail:
            with ui.element("div").classes("yul-brand").style("padding:0 0 6px"):
                ui.label("yul").classes("yul-mark")
            for index, name in enumerate(STEPS):
                with ui.element("div").classes("yul-rail-step") as item:
                    ui.label("✓" if index == DONE or index < self.step else str(index + 1)).classes(
                        "num"
                    )
                    ui.label(name)
                set_class(item, "on", index == self.step)
                set_class(item, "done", index < self.step)

        self.body.clear()
        self.message_box = self.forward = self.loaders_box = self.done_box = None
        self.budget_tiles = {}
        with self.body:
            renderers: dict[int, Callable[[], None]] = {
                TOKEN: self.render_token,
                BUDGET: self.render_budget,
                LOADERS: self.render_loaders,
                DONE: self.render_done,
            }
            with ui.element("div").classes("yul-step"):
                renderers[self.step]()
            if self.step != DONE:
                self.render_footer()

    def render_message(self) -> None:
        self.message_box = (
            ui.element("div").classes("yul-row yul-inline-state").mark("wizard-message")
        )
        self.show_message()

    def show_message(self) -> None:
        """Redraw only the message line under the step."""
        if self.message_box is None or self.message_box.is_deleted:
            return
        if self.busy:
            show_state(self.message_box, "loading", self.message or "Checking with YNAB…")
        elif self.message and self.message_is_error:
            show_state(self.message_box, "error", self.message)
        elif self.message:
            show_state(self.message_box, "ok", self.message)
        else:
            self.message_box.clear()

    def render_token(self) -> None:
        ui.label("Connect to YNAB").classes("yul-h2")
        ui.label("yul runs only on this computer and only talks to the YNAB API.").classes(
            "yul-lede"
        )
        if state().token_lost is not None:
            with ui.element("div").style("margin-bottom:12px"):
                pill("Your YNAB token is not in the keychain anymore", "warn").mark("token-lost")
                ui.label("Paste it again. Your budget, banks and accounts are kept.").classes(
                    "yul-faint yul-small"
                ).style("margin-top:4px")
        elif (load_error := state().load_error) is not None:
            with ui.element("div").style("margin-bottom:12px"):
                pill(
                    "Your saved settings could not be read; finishing setup replaces them.", "warn"
                )
                ui.label(load_error).classes("yul-faint yul-small").style("margin-top:4px")
        ui.label("Personal Access Token").classes("yul-muted yul-small")
        with ui.element("div").classes("yul-row").style("margin-top:6px;align-items:flex-start"):
            token_input = (
                ui.input(password=True, password_toggle_button=True, value=self.token)
                .props("outlined dense autofocus")
                .classes("yul-grow")
                .mark("token-input")
            )
            token_input.on_value_change(lambda e: setattr(self, "token", e.value or ""))
            token_input.on("keydown.enter", self.advance)
            button("Check", kind="primary", on_click=self.check_token).mark("check-token")
        self.render_message()
        with ui.element("div").classes("yul-faint yul-small").style("margin-top:10px"):
            ui.label("Create one in YNAB under Account Settings → Developer Settings.")
            if (name := keychain.backend_name()) is not None:
                ui.label(f"Kept in your {name}, not in a file.").style("margin-top:4px")
            else:
                ui.label(
                    f"No keychain found on this computer: kept in plain text at "
                    f"{LatestConfig.path()}"
                ).classes("yul-mono").style("margin-top:4px;word-break:break-all")

    def render_budget(self) -> None:
        ui.label("Pick a budget").classes("yul-h2")
        ui.label(f"{plural(len(self.budgets), 'budget')} for this token.").classes("yul-lede")
        grid, self.budget_tiles = budget_tiles(
            self.budgets, self.budget_id, lambda budget: self.pick_budget(str(budget.id))
        )
        grid.classes("yul-stagger")
        self.render_message()

    def pick_budget(self, budget_id: str) -> None:
        """Mark the tile in place: redrawing the grid would replay its entrance."""
        self.budget_id = budget_id
        for tile_id, tile in self.budget_tiles.items():
            set_class(tile, "on", tile_id == budget_id)
        self.say(None)
        self.update_footer()

    def render_loaders(self) -> None:
        ui.label("Banks").classes("yul-h2")
        ui.label(
            "Where each bank's statements go. You can change this later in Settings › Banks."
        ).classes("yul-lede")
        self.loaders_box = (
            ui.element("div").classes("yul-grow").style("display:flex;flex-direction:column")
        )
        self.fill_loaders()

    def fill_loaders(self) -> None:
        """The banks step below its title: reading the accounts, why that failed, or the banks."""
        box = self.loaders_box
        if box is None or box.is_deleted:
            return
        box.clear()
        with box:
            if self.busy:
                with ui.element("div").classes("yul-wait").mark("loading-accounts"):
                    loading("Reading your accounts…")
                return
            if not self.accounts_loaded:
                with ui.element("div").classes("yul-wait").mark("accounts-error"):
                    ui.label(self.message or "Could not read the accounts of this budget.").classes(
                        "yul-bad"
                    )
                    button("Try again", kind="ghost", on_click=self.load_budget).mark(
                        "accounts-retry"
                    )
                return
            if not self.accounts:
                ui.label("This budget has no open accounts.").classes("yul-muted")
            options = {account.id: account.name for account in self.accounts}
            for spec in state().loaders:
                with ui.element("div").classes("yul-map"):
                    with ui.element("div").classes("name yul-row"):
                        bank_logo(spec.key, spec.title, size=28)
                        ui.label(spec.title)
                    ui.label("→").classes("ar")
                    select = (
                        ui.select(
                            options,
                            value=self.loader_accounts.get(spec.name),
                            clearable=True,
                            label="Not set" if not self.loader_accounts.get(spec.name) else None,
                        )
                        .props("outlined dense")
                        .style("min-width:220px")
                        .mark(f"loader-{spec.key}")
                    )
                    select.on_value_change(
                        lambda e, name=spec.name: self.loader_accounts.__setitem__(name, e.value)
                    )
            self.render_message()

    def render_done(self) -> None:
        self.done_box = ui.element("div").classes("yul-wait").mark("first-copy")
        self.fill_done()

    def fill_done(self) -> ui.label:
        """The done step for the copy's state. Returns the line that follows its progress."""
        assert self.done_box is not None
        self.done_box.clear()
        with self.done_box:
            if self.copy_state == "running":
                spinner()
                ui.label(COPY_TITLE).classes("yul-h2")
                line = (
                    ui.label("Asking YNAB for your budget")
                    .classes("yul-muted")
                    .mark("copy-progress")
                )
                ui.label(COPY_NOTE).classes("yul-faint yul-small")
                return line
            if self.copy_state == "failed":
                line = ui.label("Your budget is not copied yet").classes("yul-h2")
                ui.label(self.copy_error or COPY_FAILED).classes("yul-bad").mark("copy-error")
                ui.label("yul also tries again from the top bar once it is open.").classes(
                    "yul-faint yul-small"
                )
                with ui.element("div").classes("yul-row").style("margin-top:12px"):
                    button("Try again", kind="ghost", on_click=self.first_copy).mark("copy-retry")
                    self.open_button()
                return line
            check(big=True)
            line = ui.label("You are set").classes("yul-h2")
            ui.label("Drop your first statements whenever you like.").classes("yul-lede")
            self.open_button()
            return line

    def open_button(self) -> None:
        button("Open yul", kind="primary", on_click=lambda: ui.navigate.to(shell.HOME_PATH)).mark(
            "open-yul"
        )

    def render_footer(self) -> None:
        with ui.element("div").classes("yul-wiz-foot"):
            back = button("Back", kind="ghost", on_click=self.back).mark("wizard-back")
            if self.step == TOKEN:
                back.style("visibility:hidden")
            label = "Finish" if self.step == LOADERS else "Continue"
            self.forward = button(label, kind="primary", on_click=self.advance).mark("wizard-next")
        self.update_footer()

    def update_footer(self) -> None:
        """Enable or disable Continue/Finish in place for the current step."""
        if self.forward is None or self.forward.is_deleted:
            return
        blocked = (
            self.busy
            or (self.step == BUDGET and self.budget_id is None)
            or (self.step == LOADERS and not self.accounts_loaded)
        )
        self.forward.set_enabled(not blocked)


def page() -> RedirectResponse | None:
    """`/onboarding`: shown until a config exists, then it sends the browser home."""
    if state().configured:
        return RedirectResponse(shell.HOME_PATH)
    theme.page_setup()
    Wizard().render()
    return None
