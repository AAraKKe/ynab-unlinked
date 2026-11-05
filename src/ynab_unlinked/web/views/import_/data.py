"""The Import flow's model, without NiceGUI: a file's state, why it cannot be imported, the
option choices, what is parsed and saved, and the words of the Done step and the log.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from ynab_unlinked.context_object import YnabUnlinkedContext
from ynab_unlinked.core.detect import Candidate, Detection
from ynab_unlinked.core.importing import ImportPlan, ImportResult, parse_transactions
from ynab_unlinked.entities.registry import AUTO, LoaderOption, LoaderSpec
from ynab_unlinked.models import Transaction
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
    """The loader has no account yet, the user picks one."""
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


def parse_file(
    spec: LoaderSpec, path: Path, options: dict[str, str], base: YnabUnlinkedContext[Any]
) -> list[Transaction]:
    """Read the file with the bank and these option values. Blocking: run it through io_bound."""
    context = dataclasses.replace(base, extras=spec.context_extras(options))
    return parse_transactions(spec.build(options), path, context)


def chosen_accounts(items: Sequence[ImportFile]) -> list[tuple[str, str]]:
    """(loader config key, account id) of the files whose account was picked on the row."""
    return [
        (item.candidate.loader.name, item.account_id)
        for item in items
        if item.candidate and item.account_chosen and item.account_id
    ]


def done_summary(duplicates: int, skipped: int, failed: int) -> str:
    """The line under the Done title: duplicates YNAB rejected, rows skipped, files failed."""
    lede = (
        f"YNAB rejected {duplicates} as duplicate{'' if duplicates == 1 else 's'}. "
        f"{skipped} {'was' if skipped == 1 else 'were'} already there and "
        f"{'was' if skipped == 1 else 'were'} skipped."
    )
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
    }
    message = f"Imported {result.created} transactions to {account_name} from {file}"
    return message, details


__all__ = [
    "FILE_COLORS",
    "OTHER_FILE_COLOR",
    "STEPS",
    "YEARS_OFFERED",
    "ImportFile",
    "Status",
    "chosen_accounts",
    "done_summary",
    "file_color",
    "import_log",
    "option_choices",
    "parse_file",
    "problem_text",
    "same_file",
]
