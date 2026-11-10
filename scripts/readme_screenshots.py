"""Screenshots of every page of `yul app` for the README, taken on a made-up budget.

    uv run --with playwright python scripts/readme_screenshots.py

The app runs on a scratch home (`YUL_HOME` in a temporary folder, no keychain) with a YNAB
client that answers from the fake budget below, so it never talks to YNAB or touches your
config. Playwright drives the Chrome installed on this computer and writes the pictures to
`docs/screenshots/`.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import random
import subprocess
import sys
import tempfile
import time
import urllib.request
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "screenshots"
PORT = 8791
TOKEN = "readme-screenshots"
BUDGET_ID = "00000000-0000-4000-8000-000000000001"
START = dt.date(2024, 1, 1)


def _id(name: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"yul-demo/{name}"))


# ---------------------------------------------------------------------------------------------
# The budget: accounts, categories and three years of transactions


@dataclass(frozen=True)
class DemoAccount:
    name: str
    type: str
    on_budget: bool
    closed: bool = False

    @property
    def id(self) -> str:
        return _id(f"account/{self.name}")


CHECKING = DemoAccount("Everyday", "checking", True)
SAVINGS = DemoAccount("Savings", "savings", True)
CARD = DemoAccount("Credit card", "creditCard", True)
MEAL_CARD = DemoAccount("Meal card", "cash", True)
OLD_SAVINGS = DemoAccount("Old savings", "savings", True, closed=True)
FUND = DemoAccount("Index fund", "otherAsset", False)
SHARES = DemoAccount("Company shares", "otherAsset", False)
PENSION = DemoAccount("Pension", "otherAsset", False)
ACCOUNTS = (CHECKING, SAVINGS, CARD, MEAL_CARD, OLD_SAVINGS, FUND, SHARES, PENSION)

GROUPS: dict[str, list[str]] = {
    "Internal Master Category": ["Inflow: Ready to Assign"],
    "Bills": ["Rent", "Electricity", "Internet", "Phone"],
    "Everyday": ["Groceries", "Eating out", "Transport", "Lunch at work"],
    "Life": ["Clothing", "Hobbies", "Travel", "Gifts"],
    "Yearly": ["Insurance", "Car tax", "Subscriptions"],
    "Income": ["RSUs"],
    "Savings goals": ["Emergency fund"],
}
READY = "Inflow: Ready to Assign"
NOTES = {
    (2024, 7): "Summer in Portugal",
    (2025, 3): "Annual bonus",
    (2025, 8): "Road trip to the Alps",
    (2026, 3): "Annual bonus",
}


@dataclass
class Ledger:
    rows: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])
    count: int = 0

    def _next(self) -> str:
        self.count += 1
        return str(uuid.UUID(int=self.count, version=4))

    def add(
        self,
        account: DemoAccount,
        day: dt.date,
        euros: float,
        payee: str,
        category: str | None = None,
        cleared: str = "reconciled",
        memo: str | None = None,
    ) -> dict[str, Any]:
        row: dict[str, Any] = {
            "id": self._next(),
            "var_date": day,
            "amount": round(euros * 1000),
            "cleared": cleared,
            "approved": True,
            "account_id": account.id,
            "account_name": account.name,
            "payee_name": payee,
            "category_id": _id(f"category/{category}") if category else None,
            "category_name": category,
            "memo": memo,
            "deleted": False,
            "subtransactions": [],
        }
        self.rows.append(row)
        return row

    def transfer(
        self, source: DemoAccount, target: DemoAccount, day: dt.date, euros: float
    ) -> None:
        out = self.add(source, day, -euros, f"Transfer : {target.name}")
        into = self.add(target, day, euros, f"Transfer : {source.name}")
        out |= {"transfer_account_id": target.id, "transfer_transaction_id": into["id"]}
        into |= {"transfer_account_id": source.id, "transfer_transaction_id": out["id"]}

    def vest(self, day: dt.date, euros: float) -> None:
        """Shares as income, then moved to the shares account: a zero split, as the README says."""
        far = self.add(SHARES, day, euros, f"Transfer : {CHECKING.name}", memo="Vest")
        parent = self.add(CHECKING, day, 0, "Acme Corp", memo="Share vest")
        parent["category_name"] = "Split"
        lines = [
            (euros, "RSUs", None, None),
            (-euros, "RSUs", SHARES.id, far["id"]),
        ]
        parent["subtransactions"] = [
            {
                "id": self._next(),
                "transaction_id": parent["id"],
                "amount": round(amount * 1000),
                "category_id": _id(f"category/{category}"),
                "category_name": category,
                "transfer_account_id": transfer_account,
                "transfer_transaction_id": transfer_id,
                "deleted": False,
            }
            for amount, category, transfer_account, transfer_id in lines
        ]


def _months(until: dt.date) -> list[dt.date]:
    months, day = [], START
    while day <= until:
        months.append(day)
        day = dt.date(day.year + day.month // 12, day.month % 12 + 1, 1)
    return months


def build_ledger(today: dt.date) -> Ledger:
    rng = random.Random(7)
    ledger = Ledger()
    for account, euros in (
        (CHECKING, 2_400),
        (SAVINGS, 6_000),
        (OLD_SAVINGS, 3_500),
        (FUND, 12_000),
        (SHARES, 0),
        (PENSION, 8_500),
    ):
        ledger.add(account, START, euros, "Starting Balance", READY if account.on_budget else None)
    fund = 12_000.0
    shares = 0.0

    def on(month: dt.date, day: int) -> dt.date | None:
        date = month.replace(day=min(day, 28))
        return date if date <= today else None

    for month in _months(today):
        card_spend = 0.0

        def spend(account: DemoAccount, day: int, euros: float, payee: str, category: str) -> None:
            nonlocal card_spend
            if (date := on(month, day)) is None:  # noqa: B023 (called inside the loop only)
                return
            cleared = "cleared" if (today - date).days < 12 else "reconciled"
            ledger.add(account, date, -round(euros, 2), payee, category, cleared)
            if account is CARD:
                card_spend += round(euros, 2)

        if date := on(month, 25):
            ledger.add(CHECKING, date, 3_450 if month.year < 2025 else 3_620, "Acme Corp", READY)
        if month.month == 3 and (date := on(month, 26)):
            ledger.add(CHECKING, date, 4_200, "Acme Corp", READY, memo="Bonus")
        if date := on(month, 1):
            ledger.add(MEAL_CARD, date, 160, "Cobee", READY)
        if month.month in (2, 5, 8, 11) and (date := on(month, 15)):
            vest = round(rng.uniform(2_200, 2_900), 2)
            ledger.vest(date, vest)
            shares += vest

        spend(CHECKING, 1, 1_100, "Landlord", "Rent")
        spend(CHECKING, 6, 45, "Fibra Net", "Internet")
        spend(CHECKING, 6, 20, "Mobile Co", "Phone")
        winter = month.month in (12, 1, 2)
        spend(
            CHECKING,
            9,
            rng.uniform(95, 140) if winter else rng.uniform(55, 85),
            "Power Co",
            "Electricity",
        )
        for day in (3, 10, 17, 24):
            spend(
                CARD,
                day,
                rng.uniform(70, 115),
                rng.choice(["Mercadona", "Lidl", "Market"]),
                "Groceries",
            )
        if rng.random() < 0.15 and (date := on(month, 19)):
            ledger.add(
                CARD, date, round(rng.uniform(15, 40), 2), "Mercadona", "Groceries", memo="Refund"
            )
        for _ in range(rng.choice([1, 2, 2, 3, 6])):
            spend(
                CARD,
                rng.randint(2, 27),
                rng.uniform(25, 75),
                rng.choice(["Tapas bar", "Pizzeria", "Sushi"]),
                "Eating out",
            )
        spend(CARD, 12, rng.uniform(55, 95), "Metro", "Transport")
        for day in (8, 15, 22):
            spend(MEAL_CARD, day, rng.uniform(42, 55), "Canteen", "Lunch at work")
        if rng.random() < 0.6:
            spend(
                CARD,
                rng.randint(2, 27),
                rng.uniform(30, 180),
                rng.choice(["Zara", "Decathlon"]),
                "Clothing",
            )
        spend(CARD, 14, rng.uniform(20, 90), rng.choice(["Bookshop", "Climbing gym"]), "Hobbies")
        if month.month == 7:
            spend(CARD, 5, rng.uniform(1_500, 2_100), "Airline", "Travel")
        elif month.month in (4, 12) or rng.random() < 0.1:
            spend(CARD, 18, rng.uniform(250, 600), "Hotel", "Travel")
        if month.month == 12:
            spend(CARD, 20, rng.uniform(250, 400), "Toy shop", "Gifts")
        if month.month in (2, 8):
            spend(CHECKING, 3, 480, "Insurer", "Insurance")
        if month.month == 4:
            spend(CHECKING, 2, 140, "City council", "Car tax")
        spend(CARD, 5, 15.99, "Streaming", "Subscriptions")
        if month.month == 1:
            spend(CARD, 7, 99, "Cloud storage", "Subscriptions")

        if (date := on(month, 28)) and card_spend:
            ledger.transfer(CHECKING, CARD, date, round(card_spend, 2))
        if date := on(month, 26):
            ledger.transfer(CHECKING, FUND, date, 500)
            fund += 500
            ledger.transfer(CHECKING, SAVINGS, date, 400 if month.month != 3 else 3_000)
        if month == dt.date(2024, 6, 1):
            ledger.transfer(OLD_SAVINGS, SAVINGS, dt.date(2024, 6, 10), 3_500)
        if date := on(month, 28):
            move = round(fund * rng.gauss(0.007, 0.03), 2)
            fund += move
            ledger.add(FUND, date, move, "Market value")
            if shares:
                move = round(shares * rng.gauss(0.01, 0.06), 2)
                shares += move
                ledger.add(SHARES, date, move, "Market value")
        if month.month in (3, 6, 9, 12) and (date := on(month, 28)):
            ledger.add(PENSION, date, round(rng.uniform(600, 1_100), 2), "Balance Adjustment")
    # Imported card rows carry YNAB's import id, as a file import gives them
    seen: dict[tuple[object, ...], int] = defaultdict(int)
    for row in ledger.rows:
        if row["account_id"] == CARD.id and not str(row["payee_name"]).startswith("Transfer"):
            seen[(row["amount"], row["var_date"])] += 1
            row["import_id"] = (
                f"YNAB:{row['amount']}:{row['var_date']}:{seen[(row['amount'], row['var_date'])]}"
            )
    return ledger


# ---------------------------------------------------------------------------------------------
# The app, answering from the ledger


def serve(home: Path) -> None:
    from ynab import (
        Account,
        AccountType,
        Category,
        CategoryGroupWithCategories,
        CurrencyFormat,
        DateFormat,
        MonthSummary,
        PlanDetail,
        PlanSummary,
        SubTransaction,
        TransactionDetail,
    )

    from ynab_unlinked.web import app as web_app
    from ynab_unlinked.web import state as web_state
    from ynab_unlinked.ynab_api import Client

    today = dt.date.today()
    ledger = build_ledger(today)
    transactions = [
        TransactionDetail.model_validate(
            row
            | {
                "subtransactions": [
                    SubTransaction.model_validate(s) for s in row["subtransactions"]
                ]
            }
        )
        for row in ledger.rows
    ]
    totals: dict[str, int] = defaultdict(int)
    for row in ledger.rows:
        totals[str(row["account_id"])] += row["amount"]
    uncleared: dict[str, int] = defaultdict(int)
    for row in ledger.rows:
        if row["cleared"] == "uncleared":
            uncleared[str(row["account_id"])] += row["amount"]
    currency = CurrencyFormat(
        iso_code="EUR",
        example_format="1.234,56 €",
        decimal_digits=2,
        decimal_separator=",",
        symbol_first=False,
        group_separator=".",
        currency_symbol="€",
        display_symbol=True,
    )
    accounts = [
        Account(
            id=uuid.UUID(account.id),
            name=account.name,
            type=AccountType(account.type),
            on_budget=account.on_budget,
            closed=account.closed,
            balance=totals[account.id],
            cleared_balance=totals[account.id] - uncleared[account.id],
            uncleared_balance=uncleared[account.id],
            transfer_payee_id=uuid.UUID(_id(f"payee/{account.name}")),
            deleted=False,
        )
        for account in ACCOUNTS
    ]
    groups = [
        CategoryGroupWithCategories(
            id=uuid.UUID(_id(f"group/{group}")),
            name=group,
            hidden=False,
            internal=group.startswith("Internal"),
            deleted=False,
            categories=[
                Category(
                    id=uuid.UUID(_id(f"category/{name}")),
                    category_group_id=uuid.UUID(_id(f"group/{group}")),
                    name=name,
                    hidden=False,
                    internal=group.startswith("Internal"),
                    budgeted=0,
                    activity=0,
                    balance=0,
                    deleted=False,
                )
                for name in names
            ],
        )
        for group, names in GROUPS.items()
    ]
    months = [
        MonthSummary(
            month=month,
            note=NOTES.get((month.year, month.month)),
            income=0,
            budgeted=0,
            activity=0,
            to_be_budgeted=0,
            deleted=False,
        )
        for month in _months(today)
    ]
    plan = PlanDetail(
        id=uuid.UUID(BUDGET_ID),
        name="Household",
        date_format=DateFormat(format="DD/MM/YYYY"),
        currency_format=currency,
    )

    class DemoClient(Client):
        def budgets(self, include_accounts: bool = False) -> list[PlanSummary]:
            return [
                PlanSummary(id=plan.id, name=plan.name, currency_format=currency, accounts=accounts)
            ]

        def budget(self, budget_id: str) -> PlanDetail:
            return plan

        def accounts(self, budget_id: str) -> list[Account]:
            return accounts

        def account(self, budget_id: str, account_id: str) -> Account:
            return next(a for a in accounts if str(a.id) == account_id)

        def categories(self, budget_id: str) -> list[CategoryGroupWithCategories]:
            return groups

        def months(self, budget_id: str) -> list[MonthSummary]:
            return months

        def transactions(self, budget_id, account_id=None, since_date=None):
            return [
                t
                for t in transactions
                if (account_id is None or str(t.account_id) == account_id)
                and (since_date is None or t.var_date >= since_date)
            ]

        def transactions_with_knowledge(self, budget_id, since_date=None):
            return transactions, 1

        def transactions_delta(self, budget_id, server_knowledge):
            return [], 1

        def transaction_exists(self, budget_id: str, transaction_id: str) -> bool:
            return True

        def api(self, api_name):
            raise RuntimeError(f"the demo budget does not reach YNAB ({api_name})")

    def tracked(account: DemoAccount) -> dict[str, Any]:
        bucket = {"otherAsset": "assets", "savings": "savings", "creditCard": "debt"}.get(
            account.type, "cash"
        )
        return {
            "id": account.id,
            "name": account.name,
            "type": account.type,
            "bucket": bucket,
            "track_balance": account is PENSION,
            "counted": True,
        }

    config = {
        "api_key": "demo-token",
        "budget": {
            "id": BUDGET_ID,
            "name": "Household",
            "date_format": "DD/MM/YYYY",
            "currency_format": {
                "iso_code": "EUR",
                "decimal_digits": 2,
                "decimal_separator": ",",
                "symbol_first": False,
                "group_separator": ".",
                "currency_symbol": "€",
                "display_symbol": True,
            },
        },
        "last_reconciliation_date": None,
        "loaders": {
            "sabadell": {"account_id": CARD.id, "options": {}},
            "cobee": {"account_id": MEAL_CARD.id, "options": {}},
        },
        "accounts": [tracked(a) for a in ACCOUNTS if not a.closed],
        "adjustments": {
            "memo": "Balance adjustment by yul",
            "payee": "Balance Adjustment",
            "cleared": "cleared",
        },
        "debt_mappings": [],
        "finances": {
            "not_spending": [],
            "goal_category_id": _id("category/Emergency fund"),
            "returns": {},
        },
        "version": "V4",
    }
    (home / "config.json").write_text(json.dumps(config, indent=2))

    web_state.Client = DemoClient
    web_app.new_token = lambda: TOKEN
    web_app.run(port=PORT, open_browser=False)


# ---------------------------------------------------------------------------------------------
# The pictures

WIDTH = 1440
HEIGHTS = {"import": 480, "reconcile": 760, "settings": 880}
"""Pages with little on them are cut short of the window's 960."""
STATEMENT = "statement"
"""Drops a made-up Sabadell statement on the page instead of clicking."""

SHOTS: list[tuple[str, str, str | None]] = [
    # file, path, text of something to click first
    ("home", "/", None),
    ("import", "/import", STATEMENT),
    ("reconcile", "/reconcile", None),
    ("networth-overview", "/networth", None),
    ("networth-months", "/networth?tab=months", None),
    ("networth-movers", "/networth?tab=movers", None),
    ("cashflow", "/cashflow", None),
    ("spending", "/spending", None),
    ("spending-category", "/spending", "Eating out"),
    ("settings", "/settings?tab=accounts", None),
]


def sabadell_statement(today: dt.date, folder: Path) -> Path:
    """A Sabadell card statement of the last days: what the card already has, and three new rows."""
    rows = [
        (row["var_date"], row["payee_name"], -row["amount"] / 1000)
        for row in build_ledger(today).rows
        if row["account_id"] == CARD.id
        and not str(row["payee_name"]).startswith("Transfer")
        and (today - row["var_date"]).days < 8
    ]
    rows += [
        (today - dt.timedelta(days=1), "Bakery", 6.40),
        (today - dt.timedelta(days=1), "Petrol station", 52.18),
        (today, "Cinema", 19.00),
    ]

    def euros(amount: float) -> str:
        return f"{amount:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") + "EUR"

    lines = [
        "Contrato: 000000000000",
        "Titular: NOMBRE APELLIDO",
        "",
        "Límite de crédito: 3.000,00 EUR",
        "",
        "FECHA|CONCEPTO|LOCALIDAD|IMPORTE",
        *(
            f"{day:%d/%m}|{payee.upper()}|MADRID|{euros(amount)}"
            for day, payee, amount in sorted(rows, reverse=True)
        ),
    ]
    path = folder / "movimientos.txt"
    path.write_text("\r\n".join(lines), encoding="cp1252")
    return path


def shoot() -> None:
    from playwright.sync_api import sync_playwright  # pyright: ignore[reportMissingImports]

    OUT.mkdir(parents=True, exist_ok=True)
    base = f"http://127.0.0.1:{PORT}"
    with (
        tempfile.TemporaryDirectory(prefix="yul-statement-") as folder,
        sync_playwright() as playwright,
    ):
        statement = sabadell_statement(dt.date.today(), Path(folder))
        browser = playwright.chromium.launch(channel="chrome")
        page = browser.new_page(viewport={"width": WIDTH, "height": 960}, device_scale_factor=1.5)
        page.goto(f"{base}/?token={TOKEN}")
        page.wait_for_load_state("networkidle")
        time.sleep(4)  # the first sync
        for name, path, click in SHOTS:
            page.goto(f"{base}{path}")
            page.wait_for_load_state("networkidle")
            time.sleep(2.5)  # charts animate in
            if click == STATEMENT:
                page.locator("input[type=file]").first.set_input_files(str(statement))
                time.sleep(3)
            elif click:
                page.get_by_text(click, exact=True).last.click()
                time.sleep(2)
            height = HEIGHTS.get(name, 960)
            page.screenshot(
                path=str(OUT / f"{name}.png"),
                clip={"x": 0, "y": 0, "width": WIDTH, "height": height},
            )
            print(f"wrote {OUT / name}.png")
        browser.close()


def main() -> None:
    if sys.argv[1:2] == ["--serve"]:
        serve(Path(os.environ["YUL_HOME"]))
        return
    with tempfile.TemporaryDirectory(prefix="yul-screenshots-") as home:
        env = os.environ | {"YUL_HOME": home, "YUL_NO_KEYCHAIN": "1"}
        server = subprocess.Popen([sys.executable, __file__, "--serve"], env=env)
        try:
            for _ in range(100):
                if server.poll() is not None:
                    raise SystemExit("the app did not start")
                try:
                    urllib.request.urlopen(f"http://127.0.0.1:{PORT}/", timeout=1)
                    break
                except OSError:
                    time.sleep(0.2)
            shoot()
        finally:
            server.terminate()
            server.wait()


if __name__ == "__main__":
    main()
