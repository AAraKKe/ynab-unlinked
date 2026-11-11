"""The Import flow's model, without NiceGUI: a file's state, why it cannot be imported, the
option choices, what is parsed and saved, and the words of the Done step and the log.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from ynab_unlinked.config import LatestConfig, LoaderConfig
from ynab_unlinked.core.accounts import AccountState, account_state
from ynab_unlinked.core.detect import Candidate, Detection
from ynab_unlinked.core.importing import (
    ImportPlan,
    ImportResult,
    ImportRow,
    RowStatus,
    Twin,
)
from ynab_unlinked.entities.registry import AUTO, LoaderOption, LoaderSpec
from ynab_unlinked.formatter import Formatter
from ynab_unlinked.models import Transaction, milliunits
from ynab_unlinked.store import ExcludedRow, StoredAccount
from ynab_unlinked.text import import_message
from ynab_unlinked.web.wording import plural

STEPS = ("Files", "Review", "Done")
FILE_COLORS = {
    "xlsx": "#1f8a5b",
    "xls": "#1f8a5b",
    "txt": "#5b63d6",
    "html": "#c2622a",
    "pdf": "#c2413a",
}
OTHER_FILE_COLOR = "#64748b"
YEARS_OFFERED = 3


class Status(StrEnum):
    DETECTING = "detecting"
    CHOOSE = "choose"
    """Several loaders read the file, the user picks one."""
    ACCOUNT = "account"
    """The loader has no account yet, or YNAB closed or deleted its saved one: the user picks
    one (`problem` says why when the saved one is gone)."""
    PLANNING = "planning"
    READY = "ready"
    ERROR = "error"
    """A loader was chosen but the file could not be read with it, or YNAB failed."""
    UNSUPPORTED = "unsupported"
    """No loader reads the file. Kept, greyed, and ignored."""


@dataclass(eq=False)
class ImportFile:
    key: int
    name: str
    size: int
    path: Path
    status: Status = Status.DETECTING
    detection: Detection | None = None
    candidate: Candidate | None = None
    account_id: str | None = None
    account_chosen: bool = False
    """Picked on the row: saved to the config when the import is confirmed."""
    plan: ImportPlan | None = None
    problem: str | None = None
    digest: str = ""
    """SHA-256 of the bytes, to take a file dropped twice once."""
    open: bool = False
    version: int = 0
    """Bumped on every change, so an answer for an older state is dropped."""

    @property
    def suffix(self) -> str:
        return self.path.suffix[1:].lower()

    @property
    def blocking(self) -> bool:
        return self.status not in (Status.READY, Status.UNSUPPORTED)


def file_color(suffix: str) -> str:
    return FILE_COLORS.get(suffix, OTHER_FILE_COLOR)


def same_file(item: ImportFile, others: Sequence[ImportFile]) -> ImportFile | None:
    """The file already in the import with the same bytes as `item`, if any."""
    return next(
        (
            other
            for other in others
            if other is not item and other.digest and other.digest == item.digest
        ),
        None,
    )


def mark_repeated(item: ImportFile, others: Sequence[ImportFile]) -> None:
    """Grey out `item` when the same bytes are already in the import."""
    if (first := same_file(item, others)) is not None:
        item.status = Status.UNSUPPORTED
        item.problem = f"Already in this import as {first.name}"


def take_candidate(item: ImportFile, candidate: Candidate, saved: LoaderConfig | None) -> bool:
    """Read the file with `candidate` from now on, `saved` being its bank's settings.

    False when the bank is turned off: the file is then unsupported. Otherwise the plan is
    dropped, and the account comes from the settings unless one was picked on the row for
    this bank.
    """
    if saved is not None and not saved.enabled:
        item.candidate = candidate
        item.status = Status.UNSUPPORTED
        item.problem = f"{candidate.loader.title} is turned off in Settings › Banks"
        return False
    item.version += 1
    previous, item.candidate = item.candidate, candidate
    item.plan = None
    if previous is None or previous.loader != candidate.loader:
        item.account_chosen = False
    if not item.account_chosen:
        item.account_id = saved.account_id if saved else None
    return True


def forget_gone_account(item: ImportFile, accounts: Sequence[StoredAccount] | None) -> None:
    """Drop the saved account of `item` when YNAB closed or deleted it, saying so in
    `problem`: the file then asks for another one, since YNAB would take the rows into a
    closed account and show them nowhere.

    `accounts` are the budget's (closed ones included); None when they could not be read,
    and the saved account is kept: the plan then fails on YNAB's own error. An account
    picked on the row is never dropped, it was one of the open ones.
    """
    item.problem = None
    if item.candidate is None or item.account_id is None or item.account_chosen:
        return
    if accounts is None:
        return
    if (gone := account_state(item.account_id, accounts)) is AccountState.OPEN:
        return
    item.account_id = None
    item.problem = (
        f"The account saved for {item.candidate.loader.title} {gone.reason}. Pick another one."
    )


def account_label(account_id: str, names: Mapping[str, str], config: LatestConfig) -> str:
    """The name of an account: from the budget, else from the settings, else its id."""
    if (name := names.get(account_id)) is not None:
        return name
    if (account := config.account(account_id)) is not None:
        return account.name
    return account_id


def problem_text(detection: Detection, specs: Sequence[LoaderSpec]) -> str:
    """Why a file without a usable loader cannot be imported."""
    if detection.candidates:
        errors = "; ".join(f"{c.loader.title}: {c.error}" for c in detection.candidates)
        return f"Could not be read. {errors}"
    if readers := [spec.title for spec in specs if spec.accepts(detection.input_file)]:
        return f"Does not look like a statement from {', '.join(readers)}"
    supported = sorted({str(t.value) for spec in specs for t in spec.input_types})
    return f"No bank exports this kind of file. Supported: {', '.join(supported)}"


def option_choices(option: LoaderOption, current: str, today: dt.date) -> list[str]:
    if option.choices:
        return [choice for choice in option.choices if choice != AUTO]
    if option.key == "year":
        years = [str(today.year - offset) for offset in range(YEARS_OFFERED)]
        return years if current in years else [current, *years]
    return [current]


def read_file(
    spec: LoaderSpec, path: Path, options: dict[str, str]
) -> tuple[tuple[Transaction, ...] | None, str | None]:
    """Read the file with the bank and these option values, as (transactions, None) or
    (None, why it failed). Blocking: run it through io_bound."""
    try:
        return tuple(spec.build(options).parse(path) or ()), None
    except Exception as error:
        return None, str(error)


def chosen_accounts(items: Sequence[ImportFile]) -> list[tuple[str, str]]:
    """(loader config key, account id) of the files whose account was picked on the row."""
    return [
        (item.candidate.loader.name, item.account_id)
        for item in items
        if item.candidate and item.account_chosen and item.account_id
    ]


STATUS_LABELS = {
    RowStatus.NEW: "new",
    RowStatus.MAYBE_IN_YNAB: "may be in YNAB",
    RowStatus.IN_YNAB: "already in YNAB",
    RowStatus.MATCHED: "matched in YNAB",
    RowStatus.EXCLUDED: "left out",
}
"""The tag of a row, in the order the legend lists them."""

STATUS_MEANINGS = {
    RowStatus.NEW: "Sent to YNAB when you import.",
    RowStatus.MAYBE_IN_YNAB: (
        "Has the same amount as a transaction you entered by hand and matched in YNAB, so it "
        "is probably there already. Not sent unless you choose Import anyway."
    ),
    RowStatus.IN_YNAB: "Imported before. Never sent twice.",
    RowStatus.MATCHED: (
        "YNAB matched it with a transaction you entered by hand. It is there, and never sent again."
    ),
    RowStatus.EXCLUDED: (
        "You left it out. Remembered on this computer until you include it again, here or in "
        "Settings › Data & privacy."
    ),
}
"""What each tag means, as the legend above the rows says it."""


def statuses_shown(plans: Sequence[ImportPlan]) -> list[RowStatus]:
    """The statuses the rows of these plans have, in the legend's order."""
    present = {row.status for plan in plans for row in plan.rows}
    return [status for status in STATUS_LABELS if status in present]


def left_out_count(plan: ImportPlan) -> int:
    """Rows the user left out of imports."""
    return len(plan.with_status(RowStatus.EXCLUDED))


def held_count(plan: ImportPlan) -> int:
    """Rows not sent because they may be in YNAB, until the user decides."""
    return len(plan.with_status(RowStatus.MAYBE_IN_YNAB))


def twin_note(twin: Twin, formatter: Formatter) -> str:
    """Why a row may be in YNAB: the transaction there it looks like."""
    return (
        f"Same amount as {twin.payee or 'a transaction'} on {formatter.format_date(twin.date)} "
        "in YNAB"
    )


def excluded_row(account_id: str, row: ImportRow) -> ExcludedRow:
    """What the store keeps of a row the user leaves out."""
    return ExcludedRow(
        account_id=account_id,
        import_id=row.import_id,
        date=row.transaction.date,
        amount=milliunits(row.transaction.amount),
        payee=row.transaction.payee,
    )


def done_summary(
    duplicates: int, skipped: int, failed: int, left_out: int = 0, held: int = 0
) -> str:
    """The line under the Done title: duplicates YNAB rejected, rows skipped, left out and
    held back, files failed."""
    lede = (
        f"YNAB rejected {duplicates} as duplicate{'' if duplicates == 1 else 's'}. "
        f"{skipped} {'was' if skipped == 1 else 'were'} already there and "
        f"{'was' if skipped == 1 else 'were'} skipped."
    )
    if left_out:
        lede += f" {left_out} {'was' if left_out == 1 else 'were'} left out."
    if held:
        lede += f" {held} may be in YNAB and {'was' if held == 1 else 'were'} not sent."
    if failed:
        lede += f" {plural(failed, 'file')} failed, see above."
    return lede


def import_log(
    loader: str, file: str, account_name: str, plan: ImportPlan, result: ImportResult
) -> tuple[str, dict[str, Any]]:
    """The activity log message and details of one committed file (ARCHITECTURE 3.4)."""
    details: dict[str, Any] = {
        "loader": loader,  # the config key, what Home looks up
        "account_id": plan.account_id,
        "account_name": account_name,
        "file": file,
        "created": result.created,
        "duplicates": len(result.duplicate_import_ids),
        "skipped": plan.already_imported_count,
        "matched": len(plan.with_status(RowStatus.MATCHED)),
        "excluded": left_out_count(plan),
        "held": held_count(plan),
    }
    message = import_message(result.created, account_name, file, details["excluded"])
    return message, details
