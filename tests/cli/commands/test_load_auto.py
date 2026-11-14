import datetime as dt
import json
import shutil
from pathlib import Path

import pytest

from tests.cli.process.builders import ACCOUNT_ID, BUDGET_ID, OTHER_ACCOUNT_ID, write_config
from tests.factories import AccountFactory, ImportRowFactory
from tests.helpers import assets
from tests.helpers.config import ConfigFiles
from tests.helpers.statements import cobee_export
from tests.helpers.types import CliRunner
from tests.helpers.ynab_api import YnabClientStub
from ynab_unlinked.cli import display
from ynab_unlinked.config import ImportedFiles, LatestConfig
from ynab_unlinked.core.detect import resolve_options
from ynab_unlinked.core.importing import ImportPlan, file_digest
from ynab_unlinked.entities.registry import loader
from ynab_unlinked.models import assign_import_ids
from ynab_unlinked.store import ExcludedRow, Store

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
    ynab_api.answer_accounts(
        *(AccountFactory(id=account) for account in (ACCOUNT_ID, OTHER_ACCOUNT_ID, BBVA_ACCOUNT_ID))
    )
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


def test_yes_imports_nothing_when_a_saved_account_is_closed_in_ynab(
    yul: CliRunner, accounts, ynab: YnabClientStub
):
    ynab.answer_accounts(
        AccountFactory(id=ACCOUNT_ID), AccountFactory(id=OTHER_ACCOUNT_ID, closed=True)
    )

    result = yul("load", "--yes", "auto", SABADELL, COBEE, env=WIDE)

    assert result.exit_code == 1, result.output
    assert "The account saved for Cobee is closed in YNAB." in result.output
    ynab.api("transactions").create_transaction.assert_not_called()
    # One list of the budget's accounts answers for every file
    ynab.api("accounts").get_accounts.assert_called_once()


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


def test_yes_keeps_the_rows_left_out_of_every_file(
    yul: CliRunner, accounts, ynab: YnabClientStub, store_file: Path
):
    spec = loader("sabadell")
    [first, *_] = assign_import_ids(spec.build(resolve_options(spec)).parse(Path(SABADELL)))
    Store(store_file).exclude(
        BUDGET_ID,
        ExcludedRow(
            account_id=ACCOUNT_ID,
            import_id=first.import_id,
            date=first.transaction.date,
            amount=-1,
            payee=first.transaction.payee,
        ),
    )

    result = yul("load", "--yes", "auto", SABADELL, COBEE, env=WIDE)

    assert result.exit_code == 0, result.output
    assert first.transaction.payee not in created(ynab)[ACCOUNT_ID]
    assert len(created(ynab)[ACCOUNT_ID]) == 2
    assert len(created(ynab)[OTHER_ACCOUNT_ID]) == 2


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


# ---- removing the imported files ---------------------------------------------------------


@pytest.fixture
def statement(tmp_path: Path) -> Path:
    """A copy of the Sabadell statement: these tests remove the file they import."""
    return Path(shutil.copy(SABADELL, tmp_path / "movimientos.txt"))


def imported_files_setting(config_files: ConfigFiles, choice: ImportedFiles) -> None:
    saved = json.loads(config_files.read())
    config_files.path().write_text(json.dumps(saved | {"imported_files": choice.value}))


@pytest.mark.parametrize(
    ("answer", "removed", "saved"),
    [
        pytest.param("yes", True, ImportedFiles.ASK, id="yes"),
        pytest.param("no", False, ImportedFiles.ASK, id="no"),
        pytest.param("", False, ImportedFiles.ASK, id="enter-keeps-it"),
        pytest.param("always", True, ImportedFiles.REMOVE, id="always"),
        pytest.param("never", False, ImportedFiles.KEEP, id="never"),
    ],
)
def test_the_imported_files_are_removed_when_the_user_says_so(
    yul: CliRunner,
    accounts,
    ynab: YnabClientStub,
    statement: Path,
    store_file: Path,
    answer: str,
    removed: bool,
    saved: ImportedFiles,
):
    digest = file_digest(statement)

    result = yul("load", "auto", str(statement), input=f"y\n{answer}\n", env=WIDE)

    assert result.exit_code == 0, result.output
    assert "All done! 3 transactions imported." in result.output
    assert "Remove movimientos.txt from this computer?" in result.output
    assert statement.exists() is not removed
    assert ("Removed" in result.output) is removed
    # `always` and `never` are the setting from now on
    assert LatestConfig.load().imported_files is saved
    # The app's activity lists the file, with the bytes it held
    logged = [
        (entry.message, entry.details)
        for entry in Store(store_file).activity(BUDGET_ID, kind="remove")
    ]
    assert logged == (
        [
            (
                f"Removed {statement} from this computer",
                {"count": 1, "files": [{"path": str(statement), "digest": digest}]},
            )
        ]
        if removed
        else []
    )


def test_no_answer_to_the_question_keeps_the_files(
    yul: CliRunner, accounts, ynab: YnabClientStub, statement: Path
):
    # The input ends after the confirmation: nobody is there to answer
    result = yul("load", "auto", str(statement), input="y\n", env=WIDE)

    assert result.exit_code == 0, result.output
    assert "All done! 3 transactions imported." in result.output
    assert statement.exists()


@pytest.mark.parametrize(
    ("setting", "removed"),
    [
        pytest.param(ImportedFiles.ASK, False, id="ask"),
        pytest.param(ImportedFiles.REMOVE, True, id="remove"),
        pytest.param(ImportedFiles.KEEP, False, id="keep"),
    ],
)
def test_yes_never_asks_and_removes_only_when_the_setting_says_so(
    yul: CliRunner,
    accounts,
    config_files: ConfigFiles,
    ynab: YnabClientStub,
    statement: Path,
    setting: ImportedFiles,
    removed: bool,
):
    imported_files_setting(config_files, setting)

    result = yul("load", "--yes", "auto", str(statement), env=WIDE)

    assert result.exit_code == 0, result.output
    assert "from this computer?" not in result.output
    assert statement.exists() is not removed


def test_a_saved_choice_is_followed_without_asking(
    yul: CliRunner, accounts, config_files: ConfigFiles, ynab: YnabClientStub, statement: Path
):
    imported_files_setting(config_files, ImportedFiles.REMOVE)
    copy = Path(shutil.copy(statement, statement.with_name("movimientos (1).txt")))

    result = yul("load", "auto", str(statement), str(copy), input="y\n", env=WIDE)

    assert result.exit_code == 0, result.output
    assert "from this computer?" not in result.output
    # The second copy holds the same bytes: it is as imported as the first
    assert not statement.exists() and not copy.exists()


def test_declining_the_import_keeps_the_files(
    yul: CliRunner, accounts, config_files: ConfigFiles, ynab: YnabClientStub, statement: Path
):
    imported_files_setting(config_files, ImportedFiles.REMOVE)

    result = yul("load", "auto", str(statement), input="n\n", env=WIDE)

    assert result.exit_code == 0, result.output
    assert statement.exists()


def test_a_file_already_in_ynab_is_offered_for_removal_too(
    yul: CliRunner,
    accounts,
    config_files: ConfigFiles,
    ynab: YnabClientStub,
    statement: Path,
    mocker,
):
    imported_files_setting(config_files, ImportedFiles.REMOVE)
    mocker.patch(
        "ynab_unlinked.core.importing.build_import_plan",
        side_effect=lambda client, **kwargs: ImportPlan(
            kwargs["entity_name"],
            kwargs["account_id"],
            kwargs["input_file"],
            (ImportRowFactory(already_imported=True),),
        ),
    )

    result = yul("load", "auto", str(statement), env=WIDE)

    assert result.exit_code == 0, result.output
    assert "Nothing to do" in result.output
    assert not statement.exists()


def test_a_single_bank_load_offers_to_remove_its_file(
    yul: CliRunner, accounts, ynab: YnabClientStub, statement: Path
):
    result = yul("load", "sabadell", str(statement), input="y\nyes\n", env=WIDE)

    assert result.exit_code == 0, result.output
    assert "Remove movimientos.txt from this computer?" in result.output
    assert not statement.exists()


def test_a_file_that_changes_during_the_import_is_not_removed(
    yul: CliRunner,
    accounts,
    config_files: ConfigFiles,
    ynab: YnabClientStub,
    statement: Path,
    store_file: Path,
):
    imported_files_setting(config_files, ImportedFiles.REMOVE)

    def downloaded_again(*args: object, **kwargs: object) -> object:
        statement.write_text("a newer statement")
        return ynab.api("transactions").create_transaction.return_value

    ynab.api("transactions").create_transaction.side_effect = downloaded_again

    result = yul("load", "--yes", "auto", str(statement), env=WIDE)

    assert result.exit_code == 0, result.output
    assert "it changed since it was imported" in result.output
    assert statement.read_text() == "a newer statement"
    assert Store(store_file).activity(BUDGET_ID, kind="remove") == []
