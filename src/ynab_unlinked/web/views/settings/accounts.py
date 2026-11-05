"""Settings › Accounts: a card per open account, in the section of its bucket."""

from __future__ import annotations

from typing import TYPE_CHECKING

from nicegui import ui

from ynab_unlinked.buckets import Bucket
from ynab_unlinked.config import LatestConfig, TrackedAccount
from ynab_unlinked.web import accounts as tracking
from ynab_unlinked.web import shell
from ynab_unlinked.web.accounts import STALE_AFTER_DAYS
from ynab_unlinked.web.buckets import SETTINGS_ORDER, STYLES
from ynab_unlinked.web.components import card_switch, glass_card, icon, pill, section_title
from ynab_unlinked.web.state import state
from ynab_unlinked.web.views.settings.common import open_accounts

if TYPE_CHECKING:
    from ynab_unlinked.web.views.settings import Settings


BY_HAND_HINT = (
    f"You enter this balance yourself. yul reminds you when it is older than {STALE_AFTER_DAYS} "
    "days and shows the pencil first in Net worth."
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
            for bucket in SETTINGS_ORDER:
                ids = [i for i, row in self.rows.items() if row.bucket is bucket]
                if not ids:
                    continue
                section_title(STYLES[bucket].title, swatch=STYLES[bucket].color)
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
        with card:
            with ui.element("div").classes("yul-acc-head"):
                name = ui.label(row.name).classes("yul-acc-name yul-grow")
                name.props["title"] = row.name
                card_switch(
                    card,
                    on=on,
                    marker=f"account-{account_id}",
                    title="Counted in net worth",
                    aria_label=f"Count {row.name} in net worth",
                    on_change=lambda value: self.set_counted(account_id, value, card),
                )
            with ui.element("div").classes("yul-acc-buckets").mark(f"bucket-{account_id}"):
                for bucket in SETTINGS_ORDER:
                    choice = pill(
                        STYLES[bucket].title, "acc" if bucket is row.bucket else "default"
                    )
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

    async def set_counted(self, account_id: str, on: bool, card: ui.element) -> None:
        row = self.rows[account_id]
        if row.counted == on:
            return
        row.counted = on
        await self.save("Counted in net worth" if on else "Left out of net worth")
        self.draw_card(account_id, card)

    async def set_bucket(self, account_id: str, bucket: Bucket) -> None:
        row = self.rows[account_id]
        if row.bucket is bucket:
            return
        row.bucket = bucket
        await self.save()
        self.draw()

    async def set_by_hand(self, account_id: str, card: ui.element) -> None:
        row = self.rows[account_id]
        row.track_balance = not row.track_balance
        await self.save()
        self.draw_card(account_id, card)

    async def save(self, message: str = "Accounts saved") -> None:
        """Write the rows that differ from their defaults, keeping every other entry."""
        rows = [
            row.model_copy()
            for account_id, row in self.rows.items()
            if row != self.defaults[account_id]
        ]

        def keep_others(config: LatestConfig) -> None:
            kept = [account for account in config.accounts if account.id not in self.rows]
            config.accounts = kept + rows

        await shell.save_config(keep_others, message)


async def render(page: Settings) -> None:
    config, _ = state().require()
    ui.label(
        "Every open account counts in your net worth. Switch one off to leave it out, "
        "pick the group it belongs to, and mark the ones whose balance you enter yourself. "
        "Changes are saved as you make them."
    ).classes("yul-muted").style("margin-bottom:14px").mark("accounts-lede")

    rows: dict[str, TrackedAccount] = {}
    defaults: dict[str, TrackedAccount] = {}
    for account in await open_accounts():
        defaults[account.id] = tracking.default_account(account)
        # The name and type come from the budget, the rest from the config
        rows[account.id] = tracking.account_settings(config, account).model_copy(
            update={"name": account.name, "type": account.type}
        )
    AccountCards(rows, defaults).draw()
