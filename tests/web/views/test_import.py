import datetime as dt
import uuid
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from nicegui import ui
from nicegui.elements.upload_files import SmallFileUpload
from nicegui.testing.user import User
from pytest_mock import MockerFixture
from ynab import ApiException, TransactionClearedStatus

from tests.factories import AccountFactory, TransactionDetailFactory
from tests.helpers import assets
from tests.helpers.statements import bbva_sheet, write_xls
from tests.helpers.ynab_api import YnabClientStub
from ynab_unlinked.config import LatestConfig, LoaderConfig
from ynab_unlinked.context_object import YnabUnlinkedContext
from ynab_unlinked.core.detect import resolve_options
from ynab_unlinked.entities.registry import LoaderSpec, loader
from ynab_unlinked.models import assign_import_ids
from ynab_unlinked.web.state import AppState, state

pytestmark = pytest.mark.version("V4")

ORO = str(uuid.UUID(int=1))
MAXIMA = str(uuid.UUID(int=2))
SABADELL = assets.path("sabadell/movements.txt")
BBVA = "BBVA Credit Card"


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


def import_ids(key: str, path: Path, context: YnabUnlinkedContext) -> list[str]:
    """The import ids of a statement, read with the options detection resolves."""
    spec = loader(key)
    options = resolve_options(spec)
    entity = spec.build(options)
    context.extras = spec.context_extras(options)
    return [pending.import_id for pending in assign_import_ids(entity.parse(path, context))]


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
    context_obj: YnabUnlinkedContext,
    mocker: MockerFixture,
):
    invalidate = mocker.patch.object(AppState, "invalidate")
    sabadell_ids = import_ids("sabadell", SABADELL, context_obj)
    bbva_ids = import_ids("bbva", bbva_file, context_obj)
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
        ("Imported 2 transactions to 💳 Maxima from tarjeta_maxima.xlsx", "bbva", 2, 1, 0),
        ("Imported 2 transactions to 💳 Oro from movements.txt", "sabadell", 2, 0, 1),
    ]


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
        extras=None,
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
    accounts: LatestConfig, ynab: YnabClientStub, user: User
):
    this_year = dt.date.today().year
    await drop(user, SABADELL)
    await user.should_see("3 new / 3", marker="count-1", retries=30)
    await user.should_see(f"25/04/{this_year}")

    year = user.find(marker="option-1-year").elements.pop()
    assert isinstance(year, ui.select)
    year.set_value(str(this_year - 1))

    await user.should_see(f"25/04/{this_year - 1}", retries=30)
    await user.should_not_see(f"25/04/{this_year}")
