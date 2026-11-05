import datetime as dt
from pathlib import Path

import pytest

from tests.factories import AccountFactory, ImportRowFactory
from tests.helpers import assets
from tests.helpers.config import ConfigFiles
from tests.helpers.statements import cobee_export
from tests.helpers.types import CliRunner
from tests.helpers.ynab_api import YnabClientStub
from tests.process.builders import ACCOUNT_ID, BUDGET_ID, OTHER_ACCOUNT_ID, write_config
from ynab_unlinked import display
from ynab_unlinked.core.importing import ImportPlan
from ynab_unlinked.store import Store

pytestmark = pytest.mark.version("V4")

SABADELL = str(assets.path("sabadell/movements.txt"))
COBEE = str(assets.path("cobee/transactions.html"))
BBVA = str(assets.path("bbva/bbva.xlsx"))
BBVA_ACCOUNT_ID = "00000000-0000-0000-0000-00000000000d"
WIDE = {"COLUMNS": "200"}


@pytest.fixture
def accounts(config: str, config_files: ConfigFiles):
    """Save the accounts of the entities. The YNAB client only uploads to UUID accounts."""

    def setup(entities: dict[str, str]) -> None:
        write_config(
            config_files.path("V3"),
            loaders={name: {"account_id": account} for name, account in entities.items()},
        )

    setup({"sabadell": ACCOUNT_ID, "cobee": OTHER_ACCOUNT_ID})
    return setup


@pytest.fixture
def ynab(ynab_api: YnabClientStub) -> YnabClientStub:
    api = ynab_api.api("transactions")
    api.get_transactions_by_account.return_value.data.transactions = []
    api.create_transaction.return_value.data.duplicate_import_ids = []
    return ynab_api


def created(ynab: YnabClientStub) -> dict[str, list[str]]:
    """Payees created in YNAB, by account."""
    by_account: dict[str, list[str]] = {}
    for call in ynab.api("transactions").create_transaction.call_args_list:
        for transaction in call.kwargs["data"].transactions:
            by_account.setdefault(str(transaction.account_id), []).append(transaction.payee_name)
    return by_account


def test_every_file_is_imported_with_the_loader_detected_for_it(
    yul: CliRunner, accounts, ynab: YnabClientStub, today: dt.datetime
):
    result = yul("load", "auto", SABADELL, COBEE, input="y\n", env=WIDE)

    assert result.exit_code == 0, result.output
    assert "Sabadell" in result.output
    assert "Cobee" in result.output
    assert "Create 5 transactions from 2 files in YNAB?" in result.output
    assert created(ynab) == {
        ACCOUNT_ID: ["Barberia Docklands", "Devolucion Compra", "Viaje A Japon"],
        OTHER_ACCOUNT_ID: ["Restaurante Botin", "Cafeteria Lolina"],
    }
    assert "All done! 5 transactions imported." in result.output
    assert f"{ACCOUNT_ID}: 3" in result.output
    assert f"{OTHER_ACCOUNT_ID}: 2" in result.output


def test_three_files_are_imported_with_a_single_confirmation(
    yul: CliRunner, accounts, ynab: YnabClientStub, mocker
):
    accounts(
        {"sabadell": ACCOUNT_ID, "cobee": OTHER_ACCOUNT_ID, "BBVA Credit Card": BBVA_ACCOUNT_ID}
    )
    confirm = mocker.spy(display, "confirm")

    result = yul("load", "auto", SABADELL, COBEE, BBVA, input="y\n", env=WIDE)

    assert result.exit_code == 0, result.output
    assert confirm.call_count == 1
    assert created(ynab).keys() == {ACCOUNT_ID, OTHER_ACCOUNT_ID, BBVA_ACCOUNT_ID}


def test_declining_imports_nothing(yul: CliRunner, accounts, ynab: YnabClientStub):
    result = yul("load", "auto", SABADELL, COBEE, input="n\n", env=WIDE)

    assert result.exit_code == 0, result.output
    # Both files are shown before the question
    assert "Barberia Docklands" in result.output
    assert "Restaurante Botin" in result.output
    ynab.api("transactions").create_transaction.assert_not_called()


def test_yes_imports_every_file_without_asking(yul: CliRunner, accounts, ynab: YnabClientStub):
    result = yul("load", "--yes", "auto", SABADELL, COBEE, env=WIDE)

    assert result.exit_code == 0, result.output
    assert "in YNAB?" not in result.output
    assert created(ynab).keys() == {ACCOUNT_ID, OTHER_ACCOUNT_ID}


def test_yes_imports_nothing_when_a_bank_has_no_saved_account(
    yul: CliRunner, accounts, ynab: YnabClientStub
):
    accounts({"sabadell": ACCOUNT_ID})

    result = yul("load", "--yes", "auto", SABADELL, COBEE, env=WIDE)

    assert result.exit_code == 1, result.output
    assert "No saved account for Cobee" in result.output
    # Sabadell has an account, but importing it alone would leave the batch half done
    ynab.api("transactions").create_transaction.assert_not_called()


def test_show_lists_the_transactions_without_importing(
    yul: CliRunner, accounts, ynab: YnabClientStub
):
    result = yul("load", "--show", "auto", SABADELL, COBEE, env=WIDE)

    assert result.exit_code == 0, result.output
    assert "Restaurante Botin" in result.output
    assert "Barberia Docklands" in result.output
    ynab.api("transactions").get_transactions_by_account.assert_not_called()
    ynab.api("transactions").create_transaction.assert_not_called()


@pytest.mark.parametrize(
    ("name", "content", "message"),
    [
        pytest.param(
            "notes.doc", b"Shopping list", "no bank exports this kind of file", id="unsupported"
        ),
        pytest.param(
            "notes.txt",
            b"Shopping list",
            "does not look like a statement from Sabadell",
            id="a-supported-suffix-with-other-content",
        ),
    ],
)
def test_a_file_no_bank_reads_stops_the_whole_import(
    tmp_path: Path,
    yul: CliRunner,
    accounts,
    ynab: YnabClientStub,
    name: str,
    content: bytes,
    message: str,
):
    unknown = tmp_path / name
    unknown.write_bytes(content)

    result = yul("load", "--yes", "auto", SABADELL, str(unknown), env=WIDE)

    assert result.exit_code == 1, result.output
    assert f"{name}: {message}" in result.output
    ynab.api("transactions").create_transaction.assert_not_called()


def test_an_ambiguous_file_lists_the_candidates(
    yul: CliRunner, accounts, ynab: YnabClientStub, mocker
):
    from ynab_unlinked.core.detect import Candidate, Detection
    from ynab_unlinked.entities.registry import loader

    def candidate(key: str) -> Candidate:
        return Candidate(loader(key), 0.8, "", {}, (), None)

    mocker.patch(
        "ynab_unlinked.core.detect.detect_loaders",
        return_value=[Detection(Path(SABADELL), (candidate("sabadell"), candidate("bbva")))],
    )

    result = yul("load", "auto", SABADELL, env=WIDE)

    assert result.exit_code == 1, result.output
    assert "more than one bank reads it" in result.output
    assert "sabadell (80%" in result.output
    assert "bbva (80%" in result.output
    ynab.api("transactions").create_transaction.assert_not_called()


def test_a_file_the_detected_bank_cannot_parse_stops_the_import(
    tmp_path: Path, yul: CliRunner, accounts, ynab: YnabClientStub
):
    broken = tmp_path / "cobee.html"
    broken.write_text(cobee_export(["Transacciones", "Restaurante Botin", "-34.80 €"]))

    result = yul("load", "--yes", "auto", SABADELL, str(broken), env=WIDE)

    assert result.exit_code == 1, result.output
    assert "cobee.html: could not be read. Cobee: The input file is not valid" in result.output
    ynab.api("transactions").create_transaction.assert_not_called()


def test_choosing_the_account_asks_for_it_before_importing(
    yul: CliRunner, accounts, ynab: YnabClientStub
):
    # The saved account is OTHER_ACCOUNT_ID, the one picked is "Oro" (ACCOUNT_ID)
    accounts({"sabadell": OTHER_ACCOUNT_ID})
    ynab.api("accounts").get_accounts.return_value.data.accounts = [AccountFactory(name="Oro")]

    result = yul("load", "-a", "auto", SABADELL, input="1\ny\n", env=WIDE)

    assert result.exit_code == 0, result.output
    assert "asked on import" in result.output
    assert "Account selected: Oro" in result.output
    assert created(ynab).keys() == {ACCOUNT_ID}


def test_nothing_is_asked_when_every_transaction_is_already_in_ynab(
    yul: CliRunner, accounts, ynab: YnabClientStub, mocker
):
    mocker.patch(
        "ynab_unlinked.core.importing.build_import_plan",
        side_effect=lambda client, **kwargs: ImportPlan(
            kwargs["entity_name"],
            kwargs["account_id"],
            kwargs["input_file"],
            (ImportRowFactory(already_imported=True),),
        ),
    )
    confirm = mocker.spy(display, "confirm")

    result = yul("load", "auto", SABADELL, COBEE, env=WIDE)

    assert result.exit_code == 0, result.output
    assert "Nothing to do" in result.output
    assert confirm.call_count == 0
    ynab.api("transactions").create_transaction.assert_not_called()


def test_transactions_ynab_rejects_are_reported_across_files(
    yul: CliRunner, accounts, ynab: YnabClientStub
):
    api = ynab.api("transactions")
    api.create_transaction.return_value.data.duplicate_import_ids = ["YNAB:-1000:2025-05-01:1"]

    result = yul("load", "--yes", "auto", SABADELL, COBEE, env=WIDE)

    assert result.exit_code == 0, result.output
    # One rejected per file: 5 sent, 3 created
    assert "YNAB rejected 2 of them as already imported" in result.output
    assert "All done! 3 transactions imported." in result.output


def test_each_imported_file_is_noted_in_the_activity_log(
    yul: CliRunner, accounts, ynab: YnabClientStub, store_file: Path
):
    result = yul("load", "--yes", "auto", SABADELL, COBEE, env=WIDE)

    assert result.exit_code == 0, result.output
    entries = Store(store_file).activity(BUDGET_ID, kind="import")
    assert sorted(
        (e.details["loader"], e.details["account_id"], e.details["file"], e.details["created"])
        for e in entries
    ) == [
        ("cobee", OTHER_ACCOUNT_ID, Path(COBEE).name, 2),
        ("sabadell", ACCOUNT_ID, Path(SABADELL).name, 3),
    ]


def sent_import_ids(ynab: YnabClientStub) -> list[list[str]]:
    """The import ids of every create request, one list per file."""
    return [
        [transaction.import_id for transaction in call.kwargs["data"].transactions]
        for call in ynab.api("transactions").create_transaction.call_args_list
    ]


def test_overlapping_exports_of_one_bank_send_the_shared_row_under_the_same_id(
    tmp_path: Path, yul: CliRunner, accounts, ynab: YnabClientStub
):
    # Numbered over both files the shared row was :1 and :2, and YNAB created it twice
    first, second = tmp_path / "first.html", tmp_path / "second.html"
    first.write_text(
        cobee_export(["Transacciones", "15 May 2025", "Restaurante Botin", "-34.80 €"])
    )
    second.write_text(
        cobee_export(
            [
                "Transacciones",
                "16 May 2025",
                "Cafeteria Lolina",
                "-2.10 €",
                "15 May 2025",
                "Restaurante Botin",
                "-34.80 €",
            ]
        )
    )

    result = yul("load", "--yes", "auto", str(first), str(second), env=WIDE)

    assert result.exit_code == 0, result.output
    assert sent_import_ids(ynab) == [
        ["YNAB:-34800:2025-05-15:1"],
        ["YNAB:-2100:2025-05-16:1", "YNAB:-34800:2025-05-15:1"],
    ]


def test_the_same_file_given_twice_is_imported_once(
    tmp_path: Path, yul: CliRunner, accounts, ynab: YnabClientStub
):
    copy = tmp_path / "copy.html"
    copy.write_bytes(Path(COBEE).read_bytes())

    result = yul("load", "--yes", "auto", COBEE, str(copy), env=WIDE)

    assert result.exit_code == 0, result.output
    assert "copy.html: same file as transactions.html, imported once" in result.output
    assert created(ynab) == {OTHER_ACCOUNT_ID: ["Restaurante Botin", "Cafeteria Lolina"]}


def test_the_options_saved_for_a_bank_are_used(
    yul: CliRunner, config_files: ConfigFiles, ynab: YnabClientStub, today: dt.datetime
):
    # The same file gets the same dates, and so the same import ids, as in the app
    write_config(
        config_files.path("V3"),
        loaders={"sabadell": {"account_id": ACCOUNT_ID, "options": {"year": "2023"}}},
    )

    result = yul("load", "--show", "auto", SABADELL, env=WIDE)

    assert result.exit_code == 0, result.output
    assert "25/04/2023" in result.output
