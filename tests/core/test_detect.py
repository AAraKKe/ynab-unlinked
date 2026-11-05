import datetime as dt
from pathlib import Path

import pytest
from freezegun import freeze_time

from tests.helpers import assets
from tests.helpers.statements import cobee_export, sabadell_statement
from ynab_unlinked.context_object import YnabUnlinkedContext
from ynab_unlinked.core.detect import Candidate, Detection, detect_loaders
from ynab_unlinked.entities import Match
from ynab_unlinked.entities.registry import LoaderSpec, loader
from ynab_unlinked.exceptions import ParsingError
from ynab_unlinked.models import Transaction

pytestmark = pytest.mark.version("V3")

FIXTURES = [
    pytest.param(fixture, fixture.parent.name, id=f"{fixture.parent.name}/{fixture.name}")
    for folder in ("bbva", "sabadell", "cobee")
    for fixture in sorted(assets.path(folder).iterdir())
]

PURCHASE = Transaction(dt.date(2025, 5, 1), "Mercadona", -12.05)


def detect(input_file: Path, context: YnabUnlinkedContext) -> Detection:
    [detection] = detect_loaders([input_file], context)
    return detection


@pytest.mark.parametrize(("fixture", "expected"), FIXTURES)
def test_every_statement_has_a_single_best_loader(
    context_obj: YnabUnlinkedContext, fixture: Path, expected: str
):
    detection = detect(fixture, context_obj)

    assert detection.best is not None
    assert detection.best.loader.key == expected
    assert detection.best.transactions
    assert not detection.ambiguous


@pytest.mark.parametrize(
    ("heading", "language"),
    [
        pytest.param("Transacciones", "es", id="spanish"),
        pytest.param("Transactions", "en", id="english"),
        pytest.param("Transações", "pt", id="portuguese"),
    ],
)
def test_the_language_of_a_cobee_page_is_read_from_the_page(
    tmp_path: Path, context_obj: YnabUnlinkedContext, heading: str, language: str
):
    input_file = tmp_path / "cobee.html"
    input_file.write_text(
        cobee_export([heading, "15 May 2025", "Restaurante Botin", "-34.80 €"]), encoding="utf-8"
    )

    best = detect(input_file, context_obj).best

    assert best is not None
    assert best.options == {"language": language}
    # Read with the wrong language the page parses, but to nothing
    assert [t.payee for t in best.transactions or ()] == ["Restaurante Botin"]


def test_a_sabadell_statement_is_dated_in_the_current_year(
    tmp_path: Path, context_obj: YnabUnlinkedContext, today: dt.datetime
):
    input_file = tmp_path / "sabadell.txt"
    input_file.write_text(
        sabadell_statement(["02/01|JAN|CITY|10,00EUR", "31/12|DEC|CITY|20,00EUR"]),
        encoding="cp1252",
    )

    best = detect(input_file, context_obj).best

    assert best is not None
    assert best.options == {"year": "2025"}
    # The parser still moves December back when the statement spans the new year
    assert [t.date for t in best.transactions or ()] == [dt.date(2025, 1, 2), dt.date(2024, 12, 31)]


def test_a_december_statement_read_in_january_is_dated_last_year(
    tmp_path: Path, context_obj: YnabUnlinkedContext
):
    # YNAB refuses future dates: a December statement exported on 3 January cannot be dated
    # December of the year that just started
    input_file = tmp_path / "sabadell.txt"
    input_file.write_text(
        sabadell_statement(["30/12|DEC|CITY|20,00EUR", "02/12|DEC|CITY|10,00EUR"]),
        encoding="cp1252",
    )

    with freeze_time("2026-01-03"):
        best = detect(input_file, context_obj).best

    assert best is not None
    assert [t.date for t in best.transactions or ()] == [
        dt.date(2025, 12, 30),
        dt.date(2025, 12, 2),
    ]


@pytest.mark.parametrize(
    ("key", "statement", "saved", "expected"),
    [
        pytest.param(
            "sabadell",
            sabadell_statement(["02/01|JAN|CITY|10,00EUR"]),
            {"year": "2023"},
            {"year": "2023"},
            id="a-saved-year-wins-over-the-current-one",
        ),
        pytest.param(
            "cobee",
            cobee_export(["Transacciones", "15 May 2025", "Restaurante Botin", "-34.80 €"]),
            {"language": "en"},
            {"language": "en"},
            id="a-saved-language-wins-over-the-one-on-the-page",
        ),
        pytest.param(
            "cobee",
            cobee_export(["Transacciones", "15 May 2025", "Restaurante Botin", "-34.80 €"]),
            {"language": "auto"},
            {"language": "es"},
            id="a-saved-auto-reads-the-page",
        ),
    ],
)
def test_the_options_saved_for_a_bank_win_over_the_detected_ones(
    tmp_path: Path,
    context_obj: YnabUnlinkedContext,
    today: dt.datetime,
    key: str,
    statement: str,
    saved: dict[str, str],
    expected: dict[str, str],
):
    # Settings › Banks saves them, and the CLI and the app must read a file the same way
    spec = loader(key)
    input_file = tmp_path / ("cobee.html" if key == "cobee" else "sabadell.txt")
    input_file.write_text(statement, encoding="cp1252" if key == "sabadell" else "utf-8")
    context_obj.config.loaders[spec.name].options = saved

    best = detect(input_file, context_obj).best

    assert best is not None
    assert best.options == expected


@pytest.mark.parametrize(
    ("name", "content"),
    [
        pytest.param("notes.doc", b"Fecha|Concepto", id="a-suffix-no-loader-reads"),
        pytest.param("notes.txt", b"Shopping list", id="a-text-file-that-is-no-statement"),
        pytest.param("statement", b"", id="no-suffix"),
    ],
)
def test_a_file_no_loader_recognises_has_no_candidates(
    tmp_path: Path, context_obj: YnabUnlinkedContext, name: str, content: bytes
):
    input_file = tmp_path / name
    input_file.write_bytes(content)

    detection = detect(input_file, context_obj)

    assert detection.candidates == ()
    assert detection.best is None
    assert not detection.ambiguous


def test_files_are_detected_in_the_order_given(context_obj: YnabUnlinkedContext):
    files = [assets.path("cobee/transactions.html"), assets.path("bbva/bbva.pdf")]

    detections = detect_loaders(files, context_obj)

    assert [d.input_file for d in detections] == files
    assert [d.best.loader.key for d in detections if d.best] == ["cobee", "bbva"]


class _Unreadable:
    """Recognises every text file as its own and fails to parse it."""

    def name(self) -> str:
        return "unreadable"

    def sniff(self, input_file: Path) -> Match:
        return Match(1.0, "Claims everything")

    def parse(self, input_file: Path, context: YnabUnlinkedContext) -> list[Transaction]:
        raise ParsingError(input_file, "The layout changed")


def test_a_loader_that_cannot_parse_the_file_does_not_win(mocker, context_obj: YnabUnlinkedContext):
    sabadell = loader("sabadell")
    unreadable = LoaderSpec(
        key="unreadable",
        name="unreadable",
        title="Unreadable",
        input_types=sabadell.input_types,
        options=(),
        build=lambda options: _Unreadable(),
        extras=None,
    )
    mocker.patch("ynab_unlinked.core.detect.loaders", return_value=[unreadable, sabadell])

    detection = detect(assets.path("sabadell/movements.txt"), context_obj)

    assert [c.loader.key for c in detection.candidates] == ["sabadell", "unreadable"]
    assert detection.candidates[1].error == "The layout changed"
    assert detection.best is not None
    assert detection.best.loader.key == "sabadell"


def candidate(confidence: float, parsed: bool = True) -> Candidate:
    return Candidate(
        loader=loader("bbva"),
        confidence=confidence,
        reason="",
        options={},
        transactions=(PURCHASE,) if parsed else None,
        error=None if parsed else "Could not read it",
    )


@pytest.mark.parametrize(
    ("candidates", "best", "ambiguous"),
    [
        pytest.param([candidate(0.6)], 0, False, id="a-single-candidate-wins-whatever-its-score"),
        pytest.param(
            [candidate(0.9), candidate(0.65)], 0, False, id="a-lead-of-a-quarter-is-clear"
        ),
        pytest.param(
            [candidate(0.85), candidate(0.6)], 0, False, id="a-quarter-despite-float-rounding"
        ),
        pytest.param([candidate(0.9), candidate(0.7)], None, True, id="a-smaller-lead-is-not"),
        pytest.param(
            [candidate(0.9), candidate(0.95, parsed=False)],
            0,
            False,
            id="the-only-candidate-that-parsed",
        ),
        pytest.param([candidate(0.9, parsed=False)], None, False, id="nothing-parsed-is-a-failure"),
        pytest.param([], None, False, id="no-candidates"),
    ],
)
def test_the_best_candidate_must_be_clearly_ahead(
    candidates: list[Candidate], best: int | None, ambiguous: bool
):
    detection = Detection(input_file=Path("statement.pdf"), candidates=tuple(candidates))

    assert detection.best is (None if best is None else candidates[best])
    assert detection.ambiguous is ambiguous
