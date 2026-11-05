"""First run: token, budget, banks, then the config is written and the budget is copied.

A full screen page outside the shell: a centered glass card with the step rail on its left.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal

from fastapi.responses import RedirectResponse
from nicegui import Client as NiceClient
from nicegui import context, run, ui
from ynab import ApiException, PlanSummary

from ynab_unlinked import keychain
from ynab_unlinked.buckets import Bucket
from ynab_unlinked.config import LatestConfig, LoaderConfig
from ynab_unlinked.config.core import ConfigError
from ynab_unlinked.config.models.v2 import Budget
from ynab_unlinked.entities.registry import LoaderSpec
from ynab_unlinked.utils import budget_from_plan
from ynab_unlinked.web import theme
from ynab_unlinked.web.components import bank_logo, button, check, pill, spinner
from ynab_unlinked.web.state import state
from ynab_unlinked.ynab_api import Client

STEPS = ("Token", "Budget", "Banks", "Done")
TOKEN, BUDGET, LOADERS, DONE = range(len(STEPS))

COPY_TITLE = "Copying your budget from YNAB"
COPY_NOTE = "The first time can take a minute."
COPY_FAILED = "Could not copy your budget from YNAB. Check your connection and try again."

# Settings › Accounts titles its sections with these
BUCKET_TITLES = {
    Bucket.CASH: "Cash",
    Bucket.SAVINGS: "Savings",
    Bucket.ASSETS: "Assets",
    Bucket.DEBT: "Debt",
}

CopyState = Literal["running", "done", "failed"]


def ynab_error_message(error: Exception) -> str:
    """What to tell the user when a call to YNAB fails."""
    if isinstance(error, ApiException):
        if error.status == 401:
            return "YNAB rejected this token. Check that you copied all of it."
        if error.status == 429:
            return "YNAB is rate limiting this token. Try again in a few minutes."
        return f"YNAB answered {error.status}: {error.reason}"
    return f"Could not reach YNAB: {error}"


def copy_error_message(error: Exception) -> str:
    """What to tell the user when the first copy of the budget fails."""
    if isinstance(error, ApiException):
        return ynab_error_message(error)
    return COPY_FAILED


_NUMBER = re.compile(r"\d{4,}")


def copy_line(message: str) -> str:
    """A progress message of the copy in the user's words, with grouped figures."""
    message = message.replace("Saving to the local store", "Saving the copy on this computer")
    return _NUMBER.sub(lambda match: f"{int(match.group()):,}", message)


async def fetch_budgets(token: str) -> list[PlanSummary]:
    """The budgets a token can see, with their accounts. Raises what the SDK raises."""
    return await run.io_bound(Client(token).budgets, include_accounts=True) or []


def budget_caption(budget: PlanSummary) -> str:
    parts: list[str] = []
    if budget.currency_format is not None:
        parts.append(budget.currency_format.iso_code)
    if budget.accounts is not None:
        open_accounts = [a for a in budget.accounts if not a.closed and not a.deleted]
        parts.append(f"{len(open_accounts)} account{'s' if len(open_accounts) != 1 else ''}")
    return " · ".join(parts)


@dataclass(frozen=True)
class AccountOption:
    id: str
    name: str


class LineProgress:
    """Shows the copy's progress messages on one label, from whatever thread sends them."""

    def __init__(self, label: ui.label, client: NiceClient) -> None:
        self.label = label
        self.client = client
        self.loop = asyncio.get_running_loop()

    def _show(self, message: str) -> None:
        self.loop.call_soon_threadsafe(self._apply, copy_line(message))

    def _apply(self, text: str) -> None:
        if self.label.is_deleted:
            return
        with self.client:
            self.label.set_text(text)

    def start(self, message: str) -> None:
        self._show(message)

    def done(self, message: str | None = None) -> None:
        if message:
            self._show(message)

    def info(self, message: str) -> None:
        self._show(message)

    def warn(self, message: str) -> None:
        self._show(message)


@dataclass
class Wizard:
    step: int = TOKEN
    token: str = ""
    checked_token: str | None = None
    budgets: list[PlanSummary] = field(default_factory=list)
    budget_id: str | None = None
    budget: Budget | None = None
    accounts: list[AccountOption] = field(default_factory=list)
    loader_accounts: dict[str, str | None] = field(default_factory=dict)
    busy: bool = False
    message: str | None = None
    message_is_error: bool = False
    copy_state: CopyState = "running"
    copy_error: str | None = None

    rail: ui.element | None = None
    body: ui.element | None = None
    message_box: ui.element | None = None
    forward: ui.button | None = None
    budget_tiles: dict[str, ui.element] = field(default_factory=dict)
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
            # The same budget: the saved config only needs its token back
            kept.api_key = token
            kept.save()
            state().reload()
            with client:
                ui.navigate.to("/")
            return True
        if len(budgets) == 1:
            self.budget_id = str(budgets[0].id)
        count = len(budgets)
        self.say(f"Token works · {count} budget{'s' if count != 1 else ''} found")
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
            plan = await run.io_bound(client.budget, budget_id)
            accounts = await run.io_bound(client.accounts, budget_id) or []
            if plan is None:
                raise ValueError(f"Could not find budget with ID {budget_id}")
            budget = budget_from_plan(plan)
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
            self.draft().save()
        except (OSError, ConfigError) as error:
            self.say(f"The settings could not be saved: {error}", error=True)
            return
        state().reload()
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
                if index == self.step:
                    item.classes(add="on")
                elif index < self.step:
                    item.classes(add="done")

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
        self.message_box.clear()
        with self.message_box:
            if self.busy:
                spinner()
                ui.label(self.message or "Checking with YNAB…").classes("yul-muted")
            elif self.message and self.message_is_error:
                ui.label(self.message).classes("yul-bad")
            elif self.message:
                check()
                ui.label(self.message).classes("yul-muted")

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
        count = len(self.budgets)
        ui.label(f"{count} budget{'s' if count != 1 else ''} for this token.").classes("yul-lede")
        with ui.element("div").classes("yul-optgrid yul-stagger"):
            for budget in self.budgets:
                budget_id = str(budget.id)
                with ui.element("div").classes("yul-opt").mark(f"budget-{budget_id}") as option:
                    ui.label(budget.name)
                    ui.label(budget_caption(budget)).classes("yul-faint yul-small")
                if budget_id == self.budget_id:
                    option.classes(add="on")
                option.on("click", lambda _, budget_id=budget_id: self.pick_budget(budget_id))
                self.budget_tiles[budget_id] = option
        self.render_message()

    def pick_budget(self, budget_id: str) -> None:
        """Mark the tile in place: redrawing the grid would replay its entrance."""
        self.budget_id = budget_id
        for tile_id, tile in self.budget_tiles.items():
            if tile_id == budget_id:
                tile.classes(add="on")
            else:
                tile.classes(remove="on")
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
                    spinner()
                    ui.label("Reading your accounts…").classes("yul-muted")
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
        button("Open yul", kind="primary", on_click=lambda: ui.navigate.to("/")).mark("open-yul")

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
        return RedirectResponse("/")
    theme.page_setup()
    Wizard().render()
    return None
