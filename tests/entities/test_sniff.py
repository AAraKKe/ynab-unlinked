from pathlib import Path

import pytest

from tests.helpers import assets
from tests.helpers.statements import (
    BBVA_STATEMENT,
    COBEE_TRANSACTIONS,
    SABADELL_SHEET,
    SABADELL_TXT_TRANSACTIONS,
    cobee_export,
    sabadell_statement,
    write_pdf,
    write_xls,
)
from ynab_unlinked.core.detect import MIN_CONFIDENCE, resolve_options
from ynab_unlinked.entities import Entity, InputType
from ynab_unlinked.entities.registry import LoaderSpec, loader, loaders

LOADERS = {spec.key: spec.build(resolve_options(spec)) for spec in loaders()}

# Every statement fixture lives in the folder named after the loader that reads it
FIXTURES = [
    pytest.param(fixture, fixture.parent.name, id=f"{fixture.parent.name}/{fixture.name}")
    for folder in ("bbva", "sabadell", "cobee")
    for fixture in sorted(assets.path(folder).iterdir())
]

# The title spans the last column, which keeps the empty last cell of the header row
BBVA_SHEET = [
    ["", "", "", *["Listado de movimientos"] * 4],
    ["", "Fecha", "Tarjeta", "Concepto", "Importe", "Divisa", ""],
    ["", "11/07/2025", "4940121100362325", "Netflix.com", "-19,99", "€", ""],
]


def recognising(input_file: Path) -> set[str]:
    return {
        key
        for key, entity in LOADERS.items()
        if entity.sniff(input_file).confidence >= MIN_CONFIDENCE
    }


@pytest.mark.parametrize(("fixture", "expected"), FIXTURES)
def test_only_the_loader_of_the_bank_recognises_its_statement(fixture: Path, expected: str):
    assert recognising(fixture) == {expected}


@pytest.mark.parametrize(("fixture", "expected"), FIXTURES)
def test_an_upper_case_suffix_is_read_like_a_lower_case_one(
    tmp_path: Path, fixture: Path, expected: str
):
    # Files saved as MOVIMIENTOS.XLS or Cobee.HTML were "not supported"
    upper = tmp_path / f"{fixture.stem}{fixture.suffix.upper()}"
    upper.write_bytes(fixture.read_bytes())

    assert loader(expected).accepts(upper)
    assert recognising(upper) == {expected}


def write_text(path: Path, text: str, encoding: str = "utf-8") -> Path:
    path.write_text(text, encoding=encoding)
    return path


@pytest.mark.parametrize(
    ("build", "expected"),
    [
        pytest.param(
            lambda tmp: write_xls(tmp / "bbva.xlsx", BBVA_SHEET),
            {"bbva"},
            id="a-bbva-sheet",
        ),
        pytest.param(
            lambda tmp: write_xls(tmp / "bbva.xls", BBVA_SHEET),
            set(),
            id="a-bbva-sheet-saved-in-the-legacy-format-sabadell-uses",
        ),
        pytest.param(
            lambda tmp: write_xls(tmp / "sabadell.xlsx", SABADELL_SHEET),
            set(),
            id="a-sabadell-sheet-saved-in-the-format-bbva-uses",
        ),
        pytest.param(
            lambda tmp: write_xls(tmp / "sabadell.xls", SABADELL_SHEET[-2:]),
            {"sabadell"},
            id="a-sabadell-sheet-with-only-the-debit-section",
        ),
        pytest.param(
            lambda tmp: write_pdf(
                tmp / "people.pdf", [[["Name", "Role", "City"], ["Ana", "Dev", "Madrid"]]]
            ),
            set(),
            id="a-three-column-pdf-table-without-dated-amounts",
        ),
        pytest.param(
            lambda tmp: write_pdf(tmp / "bbva.pdf", BBVA_STATEMENT, draw_grid=False),
            set(),
            id="a-pdf-without-a-table",
        ),
        pytest.param(
            lambda tmp: write_pdf(
                tmp / "wide.pdf", [[["11/07/2025", "Netflix.com", "-19,99 €", "x"]]]
            ),
            set(),
            id="a-pdf-table-with-four-columns",
        ),
        pytest.param(
            lambda tmp: write_text(tmp / "sabadell.txt", sabadell_statement([]), encoding="cp1252"),
            set(),
            id="a-sabadell-statement-without-operations",
        ),
        pytest.param(
            lambda tmp: write_text(
                tmp / "sabadell.txt",
                "\n".join(SABADELL_TXT_TRANSACTIONS),
                encoding="cp1252",
            ),
            set(),
            id="sabadell-operations-without-the-credit-limit-line",
        ),
        pytest.param(
            lambda tmp: write_text(
                tmp / "sabadell.txt",
                sabadell_statement(SABADELL_TXT_TRANSACTIONS),
                encoding="utf-8",
            ),
            set(),
            id="a-sabadell-statement-saved-as-utf8-the-parser-cannot-read",
        ),
        pytest.param(
            lambda tmp: write_text(
                tmp / "cobee.html", cobee_export(["Movimientos", *COBEE_TRANSACTIONS[1:]])
            ),
            set(),
            id="a-page-without-the-transactions-heading",
        ),
        pytest.param(
            lambda tmp: write_text(
                tmp / "cobee.html", cobee_export(["Transacciones", "15 May 2025"], header=[])
            ),
            set(),
            id="a-cobee-page-without-any-amount",
        ),
        pytest.param(
            lambda tmp: write_text(
                tmp / "cobee.html",
                cobee_export(["Transacciones", "15 May 2025", "Ahorras €9.86"], header=[]),
            ),
            set(),
            id="a-cobee-page-whose-only-euros-are-savings-notes",
        ),
    ],
)
def test_a_file_is_recognised_by_its_content(tmp_path: Path, build, expected: set[str]):
    assert recognising(build(tmp_path)) == expected


@pytest.mark.parametrize(
    "content",
    [
        pytest.param(b"this is not a statement\n", id="text"),
        pytest.param(bytes(range(256)) * 64, id="binary"),
        pytest.param(b"", id="empty"),
    ],
)
@pytest.mark.parametrize("suffix", [f".{input_type}" for input_type in InputType])
@pytest.mark.parametrize("entity", list(LOADERS.values()), ids=list(LOADERS))
def test_a_file_that_is_not_a_statement_scores_zero(
    tmp_path: Path, entity: Entity, suffix: str, content: bytes
):
    input_file = tmp_path / f"statement{suffix}"
    input_file.write_bytes(content)

    assert entity.sniff(input_file).confidence == 0


@pytest.mark.parametrize("spec", loaders(), ids=lambda spec: spec.key)
def test_a_file_that_cannot_be_opened_scores_zero_with_the_reason(tmp_path: Path, spec: LoaderSpec):
    # A suffix the loader reads, so the sniff gets past the suffix check and fails to open it
    input_file = tmp_path / f"missing.{spec.input_types[0]}"

    match = spec.build(resolve_options(spec)).sniff(input_file)

    assert match.confidence == 0
    assert "missing" in match.reason
