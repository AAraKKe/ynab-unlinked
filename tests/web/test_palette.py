import pytest
from ynab import TransactionClearedStatus

from tests.helpers.store import upsert
from ynab_unlinked.buckets import Bucket
from ynab_unlinked.config import LatestConfig, TrackedAccount
from ynab_unlinked.store import Store, StoredAccount
from ynab_unlinked.web import palette
from ynab_unlinked.web.palette import Command

pytestmark = pytest.mark.version("V4")

RECONCILED = TransactionClearedStatus.RECONCILED

COMMANDS = [
    Command("home", "Home", palette.GO_TO, "home", path="/"),
    Command("networth", "Net worth", palette.GO_TO, "networth", path="/networth"),
    Command("months", "Net worth › Months", palette.GO_TO, "networth", path="/networth?tab=months"),
    Command(
        "settings-banks",
        "Settings › Banks",
        palette.GO_TO,
        "settings",
        path="/settings?tab=banks",
        keywords="import statements",
    ),
    Command("sync", "Sync with YNAB now", palette.ACTIONS, "refresh", action="sync"),
    Command("cafe", "Café", palette.CATEGORIES, "spending", path="/s", hint="Everyday", quiet=True),
    Command(
        "network",
        "Home network",
        palette.CATEGORIES,
        "spending",
        path="/n",
        hint="Bills",
        quiet=True,
    ),
]


def keys(query: str, limit: int = palette.LIMIT) -> list[str]:
    return [command.key for command in palette.search(COMMANDS, query, limit)]


def test_without_a_query_the_palette_lists_pages_and_actions_but_no_category():
    assert keys("") == ["home", "networth", "months", "settings-banks", "sync"]
    assert keys("   ") == keys("")


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        # The start of the title, then the start of a word, then anywhere in it
        ("net", ["networth", "months", "network"]),
        ("home", ["home", "network"]),
        ("mon", ["months"]),
        # A word after the › of a tab counts as the start of a word
        ("banks", ["settings-banks"]),
        # Keywords and hints find a command without being its title
        ("statements", ["settings-banks"]),
        ("everyday", ["cafe"]),
        # Every word has to be somewhere
        ("net months", ["months"]),
        ("net bills", ["network"]),
        ("net nothing", []),
        # Case and accents do not matter
        ("CAFE", ["cafe"]),
        ("café", ["cafe"]),
    ],
)
def test_a_query_finds_commands_best_first(query: str, expected: list[str]):
    assert keys(query) == expected


def test_the_results_of_a_query_stop_at_the_limit():
    assert keys("e", limit=2) == keys("e")[:2]
    assert len(keys("e", limit=2)) == 2
    # Without a query every page and action is listed, however many
    assert len(keys("", limit=2)) == 5


def test_the_budget_adds_its_categories_and_counted_accounts(config_v4: LatestConfig, store_file):
    config_v4.accounts = [
        TrackedAccount(id="checking", name="Checking", type="checking", bucket=Bucket.CASH),
        TrackedAccount(
            id="hidden", name="Left out", type="checking", bucket=Bucket.CASH, counted=False
        ),
    ]
    config_v4.save()
    store = Store(store_file)
    upsert(
        store,
        config_v4.budget.id,
        accounts=[
            StoredAccount("checking", "Checking", "checking", False, True, 0, 0, 0),
            StoredAccount("hidden", "Left out", "checking", False, True, 0, 0, 0),
        ],
    )

    commands = palette.budget_commands(store, config_v4)

    assert [(c.key, c.path, c.quiet) for c in commands] == [
        ("account-checking", "/networth?account=checking", True)
    ]
