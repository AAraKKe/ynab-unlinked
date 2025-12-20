from __future__ import annotations

from functools import partial

from textual.app import App
from textual.containers import Container, Grid, Horizontal, VerticalScroll
from textual.message import Message
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Footer, Header, Label, Static, Switch
from ynab import TransactionClearedStatus

from ynab_unlinked.choices import Choice
from ynab_unlinked.config import Config
from ynab_unlinked.formatter import Formatter
from ynab_unlinked.models import TransactionWithYnabData

POSITIVE_COLOR = "lightgreen"
NEGATIVE_COLOR = "lightcoral"


class AccountTable(Container):
    class IncludeUncleared(Message):
        def __init__(self, value: bool):
            self.value = value
            super().__init__()

    def __init__(self, choice: Choice, formatter: Formatter):
        self.formatter = formatter
        self.choice = choice
        self.include_uncleared = False
        # By default lets mark the account for reconciliation
        self.choice.select()
        super().__init__()

    def compose(self):
        with Container(classes="account-container"):
            with Horizontal(classes="account-table-header"):
                yield Label(self.choice.title, classes="account-title")
                yield Label(self._account_balances())
                with Horizontal(id="switch-container"):
                    yield Label("Reconcile")
                    yield Switch(self.choice.is_selected, id=f"reconcile-{self.choice.id}")
            yield self.choice_to_table()

    def _account_balances(self) -> str:
        account = self.choice.account
        balance_str = partial(
            self.formatter.format_amount,
            positive_style=POSITIVE_COLOR,
            negative_style=NEGATIVE_COLOR,
        )

        cleared_str = balance_str(account.cleared_balance / 1000)
        uncleared_str = balance_str(account.uncleared_balance / 1000)
        balance_str = balance_str(account.balance / 1000)

        return (
            f"[dim]Cleared:[/dim] {cleared_str} + "
            f"[dim]Uncleared:[/dim] {uncleared_str} "
            f"[dim]= Balance[/dim] {balance_str}"
        )

    def _cleared_status(self, choice: Choice) -> str:
        status = choice.transaction.cleared

        if choice.is_selected:
            status = TransactionClearedStatus.RECONCILED

        return TransactionWithYnabData.cleared_str(status)

    def choice_to_table(self) -> DataTable:
        table = DataTable(cursor_type="row")

        table.add_column("Date")
        table.add_column("Payee")
        table.add_column("Inflow")
        table.add_column("Outflow")
        table.add_column("Cleared Status")

        for choice in self.choice.choices:
            t = choice.transaction
            amount = t.amount / 1000
            table.add_row(
                self.formatter.format_date(t.var_date),
                t.payee_name,
                self.formatter.format_amount(amount) if amount > 0 else "",
                self.formatter.format_amount(amount) if amount < 0 else "",
                self._cleared_status(choice),
                key=choice.id,
            )

        self.log.info(table)
        return table

    def on_switch_changed(self, event: Switch.Changed):
        if event.switch.value:
            self.choice.select()
        else:
            self.choice.deselect()
        self.refresh(recompose=True)

    def select(self):
        self.query_one(Switch).value = True

    def deselect(self):
        self.query_one(Switch).value = False

    def on_data_table_row_selected(self, event: DataTable.RowSelected):
        choice_id = event.row_key.value
        if choice_id is None:
            return

        child = self.choice.to_dict().get(choice_id)
        if child is None:
            return

        child.toggle_selection()
        self.refresh(recompose=True)

    def refresh_forced_selection(self, value: bool):
        for choice in self.choice.choices:
            if value:
                # Ensure uncleared are allowed to be selected
                choice.disable_forced_selected()
            else:
                # When uncleared, a transaction must always be unslected
                forced_selection = (
                    False
                    if choice.transaction.cleared is TransactionClearedStatus.UNCLEARED
                    else None
                )
                choice.enable_forced_selected(forced_selection)

        self.refresh(recompose=True)


class ReconcileModal(ModalScreen[int]):
    def __init__(self, choices: list[Choice]):
        super().__init__()
        self.choices = choices

    def compose(self):
        accounts_lines = []
        for choice in self.choices:
            n_child_selected = sum(child.is_selected for child in choice.choices)
            counter_str = (
                "All transactions"
                if n_child_selected == len(choice.choices)
                else f"{n_child_selected} transactions"
            )
            accounts_lines.append(f"- {choice.title} ({counter_str})")

        with Grid(id="reconcile-modal"):
            yield Label("Do you want to reconcile the following accounts?", id="message")
            yield Static("\n".join(accounts_lines), id="accounts-list")
            yield Button("No", id="button-no", variant="error")
            yield Button("Yes", id="button-yes", variant="success")

    def on_button_pressed(self, event: Button.Pressed):
        if event.button.id == "button-no":
            self.dismiss(1)
        else:
            self.dismiss(0)


class Reconcile(App[int]):
    TITLE = "YNAB Unlinked"
    SUB_TITLE = "Reconcile"
    BINDINGS = [("ctrl+q", "quit", "Quit")]

    CSS_PATH = "app.tcss"

    def __init__(self, config: Config, choices: list[Choice], formatter: Formatter):
        self.config = config
        self.choices = choices
        self.formatter = formatter
        super().__init__(watch_css=True)

    def compose(self):
        yield Header()
        yield Static(
            "These are the accounts to be reconciled. "
            "You can mark the entire account for reconciliation or just some of the transactions.\n\n"
            "Marking an account to be reconciled will mark all transactions within it as reconciled as well. "
            "Only uncleared transactions will be left un-marked.\nIf you want to mark uncleared transactions as well, "
            "you can enable the switch 'Include Uncleared'.",
            id="main-description",
        )
        with VerticalScroll(id="main-container"):
            for choice in self.choices:
                yield AccountTable(choice, formatter=self.formatter)
        with Horizontal(id="button-row"):
            yield Label("Include Uncleared")
            yield Switch(False, id="uncleared-switch")
            yield Button("Deselect All", id="uncheck-all")
            yield Button("Cancel", variant="default", id="cancel-button")
            yield Button("Reconcile", variant="success", id="reconcile-button")
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed):
        button_id = event.button.id

        if button_id == "cancel-button":
            self.exit(1)

        if button_id == "uncheck-all":
            if event.button.label == "Deselect All":
                for table in self.query(AccountTable):
                    table.deselect()
                event.button.label = "Select All"
            else:
                for table in self.query(AccountTable):
                    table.select()
                event.button.label = "Deselect All"

        if button_id == "reconcile-button":
            if any(choice.is_selected or choice.has_selected_choices for choice in self.choices):

                def when_dismissed(value: int | None):
                    if value == 1:
                        return
                    self.exit(value)

                self.push_screen(ReconcileModal(self.choices), when_dismissed)
            else:
                self.exit(2)

    def on_switch_changed(self, event: Switch.Changed):
        if event.switch.id and event.switch.id == "uncleared-switch":
            for table in self.query(AccountTable):
                table.refresh_forced_selection(event.switch.value)

    async def action_quit(self):
        self.exit(2)
