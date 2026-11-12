import dataclasses
import datetime as dt
import uuid
from functools import partial
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from nicegui import ui
from nicegui.elements.upload_files import SmallFileUpload
from nicegui.testing.user import User
from pytest_mock import MockerFixture
from ynab import ApiException, TransactionClearedStatus

from tests.factories import (
    AccountFactory,
    ImportRowFactory,
    StoredAccountFactory,
    StoredTransactionFactory,
    TransactionDetailFactory,
)
from tests.helpers import assets
from tests.helpers.statements import bbva_sheet, write_xls
from tests.helpers.store import upsert
from tests.helpers.ynab_api import YnabClientStub
from ynab_unlinked.config import LatestConfig, LoaderConfig
from ynab_unlinked.core.detect import Candidate, resolve_options
from ynab_unlinked.core.importing import ImportPlan, ImportResult
from ynab_unlinked.entities.registry import LoaderSpec, loader
from ynab_unlinked.entities.sabadell.sabadell import SabadellParser
from ynab_unlinked.models import assign_import_ids
from ynab_unlinked.store import ExcludedRow, Store
from ynab_unlinked.web import shell
from ynab_unlinked.web.state import AppState, state
from ynab_unlinked.web.views.import_.data import ImportFile, forget_gone_account, import_log
from ynab_unlinked.web.wording import IMPORT_FAILED

pytestmark = pytest.mark.version("V4")

ORO = str(uuid.UUID(int=1))
MAXIMA = str(uuid.UUID(int=2))
SABADELL = assets.path("sabadell/movements.txt")
BBVA = "BBVA Credit Card"
BUDGET_ID = "00000000-0000-0000-0000-000000000001"  # the budget of the V4 config asset


@pytest.fixture
def bbva_file(tmp_path: Path) -> Path:
    return write_xls(tmp_path / "tarjeta_maxima.xlsx", bbva_sheet())


@pytest.fixture
def accounts(config_v4: LatestConfig, ynab_api: YnabClientStub) -> LatestConfig:
    """Sabadell goes to Oro and BBVA to Maxima. Request it before `user`.

    The config has no account settings: the names come from the budget.
    """
    ynab_api.api("accounts").get_accounts.return_value.data.accounts = [
        AccountFactory(id=uuid.UUID(int=1), name="💳 Oro", type="creditCard"),
        AccountFactory(id=uuid.UUID(int=2), name="💳 Maxima", type="creditCard"),
        AccountFactory(id=uuid.UUID(int=3), name="Closed", type="checking", closed=True),
    ]
    config_v4.accounts = []
    config_v4.loaders = {
        "sabadell": LoaderConfig(account_id=ORO),
        BBVA: LoaderConfig(account_id=MAXIMA),
    }
    config_v4.save()
    return config_v4


@pytest.fixture
def ynab(ynab_api: YnabClientStub) -> YnabClientStub:
    api = ynab_api.api("transactions")
    api.get_transactions_by_account.return_value.data.transactions = []
    api.create_transaction.return_value.data.duplicate_import_ids = []
    return ynab_api


def import_ids(key: str, path: Path) -> list[str]:
    """The import ids of a statement, read with the options detection resolves."""
    spec = loader(key)
    entity = spec.build(resolve_options(spec))
    return [pending.import_id for pending in assign_import_ids(entity.parse(path))]


def created(ynab: YnabClientStub) -> dict[str, list[Any]]:
    """The transactions sent to YNAB, by account."""
    by_account: dict[str, list[Any]] = {}
    for call in ynab.api("transactions").create_transaction.call_args_list:
        for transaction in call.kwargs["data"].transactions:
            by_account.setdefault(str(transaction.account_id), []).append(transaction)
    return by_account


async def drop(user: User, *paths: Path) -> None:
    """Drop files on the home page, which hands them to the import view."""
    await user.open("/")
    upload = user.find(marker="drop-upload").elements.pop()
    assert isinstance(upload, ui.upload)
    await upload.handle_uploads(
        [
            SmallFileUpload(
                name=path.name, content_type="application/octet-stream", _data=path.read_bytes()
            )
            for path in paths
        ]
    )
    await user.should_see(marker="import-files", retries=20)


def review_button(user: User) -> ui.button:
    button = user.find(marker="review").elements.pop()
    assert isinstance(button, ui.button)
    return button


async def test_statements_are_detected_reviewed_and_imported(
    accounts: LatestConfig,
    ynab: YnabClientStub,
    user: User,
    bbva_file: Path,
    mocker: MockerFixture,
):
    invalidate = mocker.patch.object(AppState, "invalidate")
    sabadell_ids = import_ids("sabadell", SABADELL)
    bbva_ids = import_ids("bbva", bbva_file)
    api = ynab.api("transactions")

    def ynab_transactions(plan_id: str, account_id: str, since_date: dt.date) -> MagicMock:
        response = MagicMock()
        # The first Sabadell row was imported before
        known = [TransactionDetailFactory(import_id=sabadell_ids[0])] if account_id == ORO else []
        response.data.transactions = known
        return response

    def create(budget_id: str, data: Any) -> MagicMock:
        response = MagicMock()
        ids = [t.import_id for t in data.transactions]
        # YNAB still holds one BBVA row the account read did not return
        response.data.duplicate_import_ids = (
            ids[:1] if str(data.transactions[0].account_id) == MAXIMA else []
        )
        return response

    api.get_transactions_by_account.side_effect = ynab_transactions
    api.create_transaction.side_effect = create

    await drop(user, SABADELL, bbva_file)

    await user.should_see("Sabadell · 95%", marker="loader-1", retries=30)
    await user.should_see("→ 💳 Oro", marker="account-1")
    await user.should_see("2 new / 3", marker="count-1", retries=30)
    await user.should_see("BBVA Credit Card · 95%", marker="loader-2", retries=30)
    await user.should_see("→ 💳 Maxima", marker="account-2")
    await user.should_see("3 new / 3", marker="count-2", retries=30)
    await user.should_see("already in YNAB")

    user.find(marker="review").click()
    await user.should_see("5 new transactions in 2 accounts")
    await user.should_see("2 new / 3", marker="review-count-1")
    await user.should_see("3 new / 3", marker="review-count-2")

    user.find(marker="import").click()

    await user.should_see("4 transactions imported", retries=30)
    await user.should_see("YNAB rejected 1 as duplicate. 1 was already there and was skipped.")
    # Reconcile and Net worth sync before showing the store again
    invalidate.assert_called_once()
    sent = created(ynab)
    assert [t.import_id for t in sent[ORO]] == sabadell_ids[1:]
    assert [t.import_id for t in sent[MAXIMA]] == bbva_ids
    assert {t.cleared for ts in sent.values() for t in ts} == {TransactionClearedStatus.CLEARED}
    assert api.create_transaction.call_count == 2

    logged = sorted(
        (
            a.message,
            a.details["loader"],
            a.details["created"],
            a.details["duplicates"],
            a.details["skipped"],
        )
        for a in state().store.activity(accounts.budget.id)
        if a.kind == "import"
    )
    assert logged == [
        (
            "Imported 2 transactions to 💳 Maxima from tarjeta_maxima.xlsx",
            "BBVA Credit Card",
            2,
            1,
            0,
        ),
        ("Imported 2 transactions to 💳 Oro from movements.txt", "sabadell", 2, 0, 1),
    ]


async def test_a_file_dropped_twice_is_imported_once(
    accounts: LatestConfig, ynab: YnabClientStub, user: User, tmp_path: Path
):
    copy = tmp_path / "copy.txt"
    copy.write_bytes(SABADELL.read_bytes())

    await drop(user, SABADELL, copy)
    await user.should_see("Already in this import as movements.txt", marker="problem-2")
    await user.should_see("3 new / 3", marker="count-1", retries=30)
    user.find(marker="review").click()
    user.find(marker="import").click()

    await user.should_see("3 transactions imported", retries=30)
    assert len(ynab.api("transactions").create_transaction.call_args_list) == 1


async def test_import_as_reconciled_sends_reconciled_transactions(
    accounts: LatestConfig, ynab: YnabClientStub, user: User
):
    await drop(user, SABADELL)
    await user.should_see("3 new / 3", marker="count-1", retries=30)
    user.find(marker="review").click()

    switch = user.find(marker="reconciled").elements.pop()
    assert isinstance(switch, ui.switch)
    switch.set_value(True)
    user.find(marker="import").click()

    await user.should_see("3 transactions imported", retries=30)
    assert {t.cleared for t in created(ynab)[ORO]} == {TransactionClearedStatus.RECONCILED}


async def test_a_file_of_a_bank_turned_off_is_skipped(
    accounts: LatestConfig, ynab: YnabClientStub, user: User
):
    accounts.loaders["sabadell"].enabled = False
    accounts.save()
    state().reload()

    await drop(user, SABADELL)

    await user.should_see(
        "Sabadell is turned off in Settings › Banks", marker="problem-1", retries=30
    )
    await user.should_see("1 file skipped")


async def test_an_unsupported_file_is_greyed_and_does_not_block_the_others(
    accounts: LatestConfig, ynab: YnabClientStub, user: User, tmp_path: Path
):
    notes = tmp_path / "notes.doc"
    notes.write_text("Shopping list")

    await drop(user, notes, SABADELL)

    await user.should_see("No bank exports this kind of file", marker="problem-1", retries=30)
    await user.should_see("3 new / 3", marker="count-2", retries=30)
    await user.should_see("1 file skipped")
    assert review_button(user).enabled
    assert "off" in user.find(marker="file-1").elements.pop().classes


async def test_an_ambiguous_file_waits_for_the_bank_to_be_chosen(
    accounts: LatestConfig, ynab: YnabClientStub, user: User, mocker: MockerFixture
):
    sabadell = loader("sabadell")
    twin = LoaderSpec(
        key="twin",
        name="twin",
        title="Twin",
        input_types=sabadell.input_types,
        options=sabadell.options,
        build=sabadell.build,
    )
    mocker.patch("ynab_unlinked.core.detect.loaders", return_value=[sabadell, twin])

    await drop(user, SABADELL)

    await user.should_see("Which bank?", retries=30)
    await user.should_see("Sabadell · 3", marker="choose-1-sabadell")
    await user.should_see("Twin · 3", marker="choose-1-twin")
    assert not review_button(user).enabled

    user.find(marker="choose-1-sabadell").click()

    await user.should_see("3 new / 3", marker="count-1", retries=30)
    assert review_button(user).enabled


async def test_a_loader_without_an_account_asks_for_one_and_saves_it_on_import(
    accounts: LatestConfig, ynab: YnabClientStub, user: User, bbva_file: Path
):
    accounts.loaders.pop(BBVA)
    accounts.save()
    state().reload()

    await drop(user, bbva_file)

    await user.should_see(marker="account-select-1", retries=30)
    assert not review_button(user).enabled
    select = user.find(marker="account-select-1").elements.pop()
    assert isinstance(select, ui.select)
    assert select.options == {ORO: "💳 Oro", MAXIMA: "💳 Maxima"}
    select.set_value(MAXIMA)

    await user.should_see("3 new / 3", marker="count-1", retries=30)
    assert LatestConfig.load().entity(BBVA) is None
    user.find(marker="review").click()
    user.find(marker="import").click()

    await user.should_see("3 transactions imported", retries=30)
    saved = LatestConfig.load().entity(BBVA)
    assert saved is not None
    assert saved.account_id == MAXIMA
    assert list(created(ynab)) == [MAXIMA]


@pytest.mark.parametrize(
    ("oro", "reason"),
    [
        ([AccountFactory(id=uuid.UUID(int=1), name="💳 Oro", closed=True)], "is closed in YNAB"),
        ([], "is no longer in the budget"),
    ],
    ids=["closed", "deleted"],
)
async def test_a_saved_account_gone_from_ynab_asks_for_another_one_and_saves_it(
    accounts: LatestConfig, ynab: YnabClientStub, user: User, oro: list, reason: str
):
    # YNAB takes transactions into a closed account and then shows them nowhere
    ynab.answer_accounts(*oro, AccountFactory(id=uuid.UUID(int=2), name="💳 Maxima"))

    await drop(user, SABADELL)

    await user.should_see(
        f"The account saved for Sabadell {reason}. Pick another one.",
        marker="account-gone-1",
        retries=30,
    )
    assert not review_button(user).enabled
    # Reading the file again with another year still says why the account is asked for
    year = user.find(marker="option-1-year").elements.pop()
    assert isinstance(year, ui.select)
    year.set_value(str(dt.date.today().year - 1))
    await user.should_see(
        f"The account saved for Sabadell {reason}. Pick another one.",
        marker="account-gone-1",
        retries=30,
    )
    select = user.find(marker="account-select-1").elements.pop()
    assert isinstance(select, ui.select)
    assert select.options == {MAXIMA: "💳 Maxima"}
    select.set_value(MAXIMA)

    await user.should_see("3 new / 3", marker="count-1", retries=30)
    user.find(marker="review").click()
    user.find(marker="import").click()

    await user.should_see("3 transactions imported", retries=30)
    assert list(created(ynab)) == [MAXIMA]
    saved = LatestConfig.load().entity("sabadell")
    assert saved is not None
    assert saved.account_id == MAXIMA


async def test_an_account_closed_after_the_file_was_read_is_asked_for_again_before_sending(
    accounts: LatestConfig, ynab: YnabClientStub, store_file: Path, user: User
):
    oro = StoredAccountFactory(id=ORO, name="💳 Oro", type="creditCard")
    maxima = StoredAccountFactory(id=MAXIMA, name="💳 Maxima", type="creditCard")
    upsert(Store(store_file), BUDGET_ID, accounts=[oro, maxima])

    await drop(user, SABADELL)
    await user.should_see("3 new / 3", marker="count-1", retries=30)
    # A sync while the file is on screen brings Oro closed in YNAB
    upsert(Store(store_file), BUDGET_ID, accounts=[dataclasses.replace(oro, closed=True)])
    state().last_sync = dt.datetime.now(dt.UTC)
    user.find(marker="review").click()
    user.find(marker="import").click()

    await user.should_see(
        "The account saved for Sabadell is closed in YNAB. Pick another one.",
        marker="account-gone-1",
        retries=30,
    )
    await user.should_see("Pick another account for movements.txt")
    assert created(ynab) == {}
    select = user.find(marker="account-select-1").elements.pop()
    assert isinstance(select, ui.select)
    assert select.options == {MAXIMA: "💳 Maxima"}
    select.set_value(MAXIMA)

    await user.should_see("3 new / 3", marker="count-1", retries=30)
    user.find(marker="review").click()
    user.find(marker="import").click()

    await user.should_see("3 transactions imported", retries=30)
    assert list(created(ynab)) == [MAXIMA]


async def test_a_failed_read_of_the_accounts_after_a_sync_keeps_the_ones_read_before(
    accounts: LatestConfig,
    ynab: YnabClientStub,
    user: User,
    bbva_file: Path,
    mocker: MockerFixture,
):
    await drop(user, SABADELL)
    await user.should_see("→ 💳 Oro", marker="account-1", retries=30)
    mocker.patch.object(AppState, "budget_accounts", side_effect=OSError("disk gone"))
    state().last_sync = dt.datetime.now(dt.UTC)

    # Dropped on the same page, where the flow read the accounts before
    upload = user.find(marker="dropzone").elements.pop()
    assert isinstance(upload, ui.upload)
    await upload.handle_uploads(
        [
            SmallFileUpload(
                name=bbva_file.name,
                content_type="application/octet-stream",
                _data=bbva_file.read_bytes(),
            )
        ]
    )

    await user.should_see("→ 💳 Maxima", marker="account-2", retries=30)
    await user.should_see("3 new / 3", marker="count-2", retries=30)


@pytest.mark.parametrize(
    ("chosen", "accounts"),
    [
        (False, None),
        (True, [StoredAccountFactory(id=ORO, closed=True)]),
    ],
    ids=["the budget's accounts could not be read", "picked on the row"],
)
def test_an_account_that_cannot_be_judged_gone_is_kept(chosen: bool, accounts: list | None):
    item = ImportFile(key=1, name="movements.txt", size=1, path=SABADELL, account_id=ORO)
    item.candidate = Candidate(loader("sabadell"), 1.0, "test", {}, (), None)
    item.account_chosen = chosen

    assert not forget_gone_account(item, accounts)

    assert item.account_id == ORO
    assert item.account_gone is None


async def test_a_ynab_failure_is_shown_on_the_row_and_can_be_retried(
    accounts: LatestConfig, ynab: YnabClientStub, user: User
):
    api = ynab.api("transactions")
    working = api.get_transactions_by_account.return_value
    api.get_transactions_by_account.side_effect = ApiException(status=401, reason="Unauthorized")

    await drop(user, SABADELL)

    await user.should_see("YNAB rejected this token", retries=30)
    await user.should_see(marker="error-1")
    assert not review_button(user).enabled

    api.get_transactions_by_account.side_effect = None
    api.get_transactions_by_account.return_value = working
    user.find(marker="retry-1").click()

    await user.should_see("3 new / 3", marker="count-1", retries=30)


async def test_changing_the_statement_year_reads_the_file_again(
    accounts: LatestConfig, ynab: YnabClientStub, user: User, mocker: MockerFixture
):
    this_year = dt.date.today().year
    # Read before 22 April, the 25/04 row would be moved back to last year
    mocker.patch(
        "ynab_unlinked.entities.sabadell.spec.SabadellParser",
        partial(SabadellParser, today=dt.date(this_year, 6, 1)),
    )
    await drop(user, SABADELL)
    await user.should_see("3 new / 3", marker="count-1", retries=30)
    await user.should_see(f"25/04/{this_year}")

    year = user.find(marker="option-1-year").elements.pop()
    assert isinstance(year, ui.select)
    year.set_value(str(this_year - 1))

    await user.should_see(f"25/04/{this_year - 1}", retries=30)
    await user.should_not_see(f"25/04/{this_year}")


async def test_the_year_saved_for_the_bank_dates_the_statement(
    accounts: LatestConfig, ynab: YnabClientStub, user: User
):
    accounts.loaders["sabadell"].options = {"year": "2023"}
    accounts.save()
    state().reload()

    await drop(user, SABADELL)

    await user.should_see("3 new / 3", marker="count-1", retries=30)
    await user.should_see("25/04/2023")


@pytest.mark.parametrize(
    "fail",
    [
        pytest.param("ynab", id="the YNAB call raises"),
        pytest.param("log", id="something after the YNAB call raises"),
    ],
)
async def test_a_failed_commit_leaves_the_flow_open_to_new_drops(
    accounts: LatestConfig, ynab: YnabClientStub, user: User, mocker: MockerFixture, fail: str
):
    if fail == "ynab":
        ynab.api("transactions").create_transaction.side_effect = ApiException(
            status=500, reason="Internal Server Error"
        )
    else:
        mocker.patch(
            "ynab_unlinked.web.views.import_.view.import_log", side_effect=RuntimeError("boom")
        )
    notify = mocker.spy(shell, "notify")

    await drop(user, SABADELL)
    await user.should_see("3 new / 3", marker="count-1", retries=30)
    user.find(marker="review").click()
    user.find(marker="import").click()
    expected = "YNAB answered 500" if fail == "ynab" else IMPORT_FAILED
    await user.should_see(expected, retries=30)

    await drop(user, SABADELL)
    await user.should_see("3 new / 3", marker="count-1", retries=30)
    assert all("Wait for the import" not in str(call.args[0]) for call in notify.call_args_list)


@pytest.mark.parametrize(
    ("created", "message"),
    [
        pytest.param(1, "Imported 1 transaction to 💳 Oro from movements.txt", id="one"),
        pytest.param(2, "Imported 2 transactions to 💳 Oro from movements.txt", id="two"),
    ],
)
def test_the_log_line_of_an_import_counts_in_words(created: int, message: str):
    plan = ImportPlan(entity_name="sabadell", account_id=ORO, input_file=SABADELL, rows=())
    result = ImportResult(created=created, duplicate_import_ids=())

    logged, _ = import_log("sabadell", "movements.txt", "💳 Oro", plan, result)

    assert logged == message


async def test_the_review_shows_money_in_with_a_plus_in_the_good_tone(
    accounts: LatestConfig, ynab: YnabClientStub, user: User
):
    await drop(user, SABADELL)
    await user.should_see("3 new / 3", marker="count-1", retries=30)
    user.find(marker="review").click()
    await user.should_see(marker="row-amount-1-2", retries=20)

    shown = [user.find(marker=f"row-amount-1-{index}").elements.pop() for index in range(3)]
    assert [
        (label.text, "in" in label.classes) for label in shown if isinstance(label, ui.label)
    ] == [
        ("-48.00€", False),
        ("+12.50€", True),
        ("-1,212.16€", False),
    ]


async def test_money_in_on_a_row_left_out_keeps_its_tone_on_the_crossed_out_row(
    accounts: LatestConfig, ynab: YnabClientStub, user: User
):
    await drop(user, SABADELL)
    await user.should_see("3 new / 3", marker="count-1", retries=30)
    user.find(marker="review").click()

    user.find(marker="leave-out-1-1").click()

    await user.should_see("left out", marker="row-status-1-1", retries=20)
    label = user.find(marker="row-amount-1-1").elements.pop()
    row = label.parent_slot.parent.parent_slot.parent
    assert (label.text, "in" in label.classes, "out" in row.classes) == ("+12.50€", True, True)


@pytest.fixture
def sabadell_first_left_out(store_file: Path) -> str:
    """The first Sabadell row, left out of imports to Oro in an earlier run. Before `user`."""
    import_id = import_ids("sabadell", SABADELL)[0]
    Store(store_file).exclude(
        BUDGET_ID,
        ExcludedRow(
            account_id=ORO, import_id=import_id, date=dt.date(2025, 1, 1), amount=-1, payee="x"
        ),
    )
    return import_id


async def test_a_row_left_out_in_the_review_is_never_sent_and_stays_left_out(
    accounts: LatestConfig, ynab: YnabClientStub, user: User
):
    first, *rest = import_ids("sabadell", SABADELL)
    await drop(user, SABADELL)
    await user.should_see("3 new / 3", marker="count-1", retries=30)
    user.find(marker="review").click()

    user.find(marker="leave-out-1-0").click()

    await user.should_see("left out", marker="row-status-1-0", retries=20)
    await user.should_see("1 left out", marker="review-left-out")
    await user.should_see("2 new transactions in 1 account", marker="review-summary")
    store = state().store
    assert [row.import_id for row in store.excluded(BUDGET_ID, ORO)] == [first]
    [entry] = store.activity(BUDGET_ID, kind="exclude")
    assert entry.message.startswith("Left ")
    assert entry.details["import_id"] == first

    user.find(marker="import").click()

    await user.should_see("2 transactions imported", retries=30)
    await user.should_see("1 was left out.", marker="done-summary")
    assert [t.import_id for t in created(ynab)[ORO]] == rest
    [logged] = store.activity(BUDGET_ID, kind="import")
    assert logged.details["excluded"] == 1


async def test_a_row_left_out_before_comes_back_crossed_out_and_can_be_included_again(
    accounts: LatestConfig, ynab: YnabClientStub, sabadell_first_left_out: str, user: User
):
    await drop(user, SABADELL)
    await user.should_see("2 new / 3", marker="count-1", retries=30)
    user.find(marker="review").click()
    await user.should_see("left out", marker="row-status-1-0")

    user.find(marker="include-1-0").click()

    await user.should_see("new", marker="row-status-1-0", retries=20)
    await user.should_see("3 new transactions in 1 account", marker="review-summary")
    store = state().store
    assert store.excluded(BUDGET_ID) == []
    assert len(store.activity(BUDGET_ID, kind="include")) == 1
    user.find(marker="import").click()
    await user.should_see("3 transactions imported", retries=30)
    assert sabadell_first_left_out in [t.import_id for t in created(ynab)[ORO]]


async def test_a_row_matched_onto_a_reconciled_transaction_is_shown_as_in_ynab(
    accounts: LatestConfig, ynab: YnabClientStub, store_file: Path, user: User
):
    first = import_ids("sabadell", SABADELL)[0]
    upsert(
        Store(store_file),
        BUDGET_ID,
        transactions=[StoredTransactionFactory(id="yul", account_id=ORO, import_id=first)],
    )
    ynab.api("transactions").get_transactions_by_account.return_value.data.transactions = [
        TransactionDetailFactory(
            id="hand",
            cleared=TransactionClearedStatus.RECONCILED,
            matched_transaction_id="yul",
        )
    ]

    await drop(user, SABADELL)

    await user.should_see("2 new / 3", marker="count-1", retries=30)
    user.find(marker="review").click()
    await user.should_see("matched in YNAB", marker="row-status-1-0")


@pytest.fixture
def first_row_matched_by_hand(ynab: YnabClientStub) -> str:
    """The first Sabadell row was imported and matched in YNAB with a reconciled transaction
    entered by hand, before the budget copy saw it: YNAB lists only that one. Before `user`."""
    first = import_ids("sabadell", SABADELL)[0]
    _, amount, date, _ = first.split(":")
    ynab.api("transactions").get_transactions_by_account.return_value.data.transactions = [
        TransactionDetailFactory(
            id="hand",
            var_date=dt.date.fromisoformat(date) + dt.timedelta(days=1),
            amount=int(amount),
            payee_name="Japan trip",
            cleared=TransactionClearedStatus.RECONCILED,
            matched_transaction_id="never-seen",
        )
    ]
    return first


async def test_a_row_that_may_be_in_ynab_is_pointed_out_and_not_sent(
    accounts: LatestConfig, ynab: YnabClientStub, first_row_matched_by_hand: str, user: User
):
    await drop(user, SABADELL)

    await user.should_see("2 new / 3", marker="count-1", retries=30)
    await user.should_see("1 to check", marker="held-1")
    await user.should_see("1 to check", marker="files-held")
    user.find(marker="review").click()
    await user.should_see("may be in YNAB", marker="row-status-1-0")
    await user.should_see("Same amount as Japan trip on", marker="row-twin-1-0")
    await user.should_see("1 to check", marker="review-held")
    await user.should_see("1 to check", marker="review-held-1")
    await user.should_see("Not sent unless you choose Import anyway", marker="status-legend")

    user.find(marker="import").click()

    await user.should_see("2 transactions imported", retries=30)
    await user.should_see("1 may be in YNAB and was not sent.", marker="done-summary")
    assert first_row_matched_by_hand not in [t.import_id for t in created(ynab)[ORO]]
    [logged] = state().store.activity(BUDGET_ID, kind="import")
    assert logged.details["held"] == 1


@pytest.mark.parametrize(
    ("button", "status", "summary", "sent"),
    [
        pytest.param("import-anyway-1-0", "new", "3 new transactions in 1 account", 3, id="sent"),
        pytest.param("leave-out-1-0", "left out", "2 new transactions in 1 account", 2, id="out"),
    ],
)
async def test_a_row_that_may_be_in_ynab_is_imported_anyway_or_left_out(
    accounts: LatestConfig,
    ynab: YnabClientStub,
    first_row_matched_by_hand: str,
    user: User,
    button: str,
    status: str,
    summary: str,
    sent: int,
):
    await drop(user, SABADELL)
    await user.should_see("2 new / 3", marker="count-1", retries=30)
    user.find(marker="review").click()
    await user.should_see("may be in YNAB", marker="row-status-1-0")

    user.find(marker=button).click()

    await user.should_see(status, marker="row-status-1-0", retries=20)
    await user.should_see(summary, marker="review-summary")
    await user.should_not_see(marker="review-held")
    await user.should_not_see(marker="legend-maybe_in_ynab")
    left_out = [row.import_id for row in state().store.excluded(BUDGET_ID, ORO)]
    assert left_out == ([first_row_matched_by_hand] if status == "left out" else [])
    user.find(marker="import").click()
    await user.should_see(f"{sent} transactions imported", retries=30)
    assert len(created(ynab)[ORO]) == sent


async def test_the_legend_explains_only_the_tags_on_screen(
    accounts: LatestConfig, ynab: YnabClientStub, user: User
):
    ynab.api("transactions").get_transactions_by_account.return_value.data.transactions = [
        TransactionDetailFactory(import_id=import_ids("sabadell", SABADELL)[0])
    ]
    await drop(user, SABADELL)
    await user.should_see("2 new / 3", marker="count-1", retries=30)
    user.find(marker="review").click()

    await user.should_see("Sent to YNAB when you import.", marker="legend-new")
    await user.should_see("Imported before. Never sent twice.", marker="legend-in_ynab")
    await user.should_not_see(marker="legend-excluded")

    user.find(marker="leave-out-1-1").click()

    await user.should_see("You left it out.", marker="legend-excluded", retries=20)


async def test_what_an_import_created_is_kept_in_the_budget_copy_at_once(
    accounts: LatestConfig, ynab: YnabClientStub, user: User
):
    first = import_ids("sabadell", SABADELL)[0]
    ynab.api("transactions").create_transaction.return_value.data.transactions = [
        TransactionDetailFactory(id="created-by-yul", import_id=first)
    ]
    await drop(user, SABADELL)
    await user.should_see("3 new / 3", marker="count-1", retries=30)
    user.find(marker="review").click()

    user.find(marker="import").click()

    await user.should_see("3 transactions imported", retries=30)
    assert state().store.import_ids(BUDGET_ID, ["created-by-yul"]) == {"created-by-yul": first}


def test_the_log_line_of_an_import_says_how_many_rows_were_left_out():
    plan = ImportPlan(
        entity_name="sabadell",
        account_id=ORO,
        input_file=SABADELL,
        rows=(
            ImportRowFactory(import_id="YNAB:-1:x:1", already_imported=True, matched=True),
            ImportRowFactory(import_id="YNAB:-2:x:1", excluded=True),
            ImportRowFactory(import_id="YNAB:-3:x:1"),
        ),
    )
    result = ImportResult(created=1, duplicate_import_ids=())

    logged, details = import_log("sabadell", "movements.txt", "💳 Oro", plan, result)

    assert logged == "Imported 1 transaction to 💳 Oro from movements.txt · 1 left out"
    assert (details["skipped"], details["matched"], details["excluded"]) == (1, 1, 1)
