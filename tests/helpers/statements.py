"""Generators for the binary fixtures under `tests/assets`.

Run `hatch run dev:python tests/helpers/statements.py` to rewrite every fixture this module
owns. They are generated rather than hand made: there is no PDF writing library in the
dependency tree, so `write_pdf` emits a minimal PDF by hand, a grid of stroked lines plus
Helvetica text placed inside it, which is what pdfplumber needs to recover a table with
its default (line based) settings.
"""

from collections.abc import Iterable, Sequence
from pathlib import Path

Row = Sequence[str]
Page = Sequence[Row]

ASSETS = Path(__file__).parents[1] / "assets"

PAGE_WIDTH = 612
PAGE_HEIGHT = 792
FONT_SIZE = 9
LINE_HEIGHT = 12
ROW_PADDING = 4
TOP = 750
LEFT = 40
COLUMN_WIDTH = 140

# A Sabadell sheet, trimmed from a real export. The statement repeats its header once the
# pending operations have been listed, and every cell is a string, amounts included.
SABADELL_SHEET: list[Row] = [
    ["Saldos y movimientos", "", "", "", "", ""],
    ["Contrato", "004880355431", "Cuenta relacionada", "0081-2714-17-0003177820", "", ""],
    ["Titular", "NOMBRE APELLIDO", "", "", "", ""],
    ["", "", "", "", "", ""],
    ["MOVIMIENTOS DE CREDITO", "", "", "", "", ""],
    ["", "", "", "", "", ""],
    ["FECHA", "CONCEPTO", "LOCALIDAD", "SIT. MOV.", "IMPORTE", ""],
    ["29/06", "JUSTEAT", "MADRID", "AUT", "26,90", "EUR(1)"],
    ["", "", "TOTAL OPERACIONES", "", "", ""],
    ["", "", "", "", "", ""],
    ["FECHA", "CONCEPTO", "LOCALIDAD", "IMPORTE", "", ""],
    ["28/06", "LOS DIAMANTES", "GRANADA", " ", "34,80", "EUR"],
    ["27/06", "DEVOLUCION COMPRA", "MADRID", " ", "-12,50", "EUR"],
    ["26/06", "UBER   *EATS", "HELP.UBER.COM", " ", "1.212,16", "EUR"],
    ["", "", "TOTAL OPERACIONES", "1.234,46", "EUR", ""],
    ["(1)Movimientos pendientes de confirmar", "", "", "", "", ""],
    ["MOVIMIENTOS DE DEBITO", "", "", "", "", ""],
    ["25/06", "LIQUIDACION TARJETA", "MADRID", " ", "99,99", "EUR"],
]

# Two header rows so a single fixture can show both where reading starts and how skipping
# rows leaves the first header behind.
XLS_SHEET: list[Row] = [
    ["Saldos y movimientos", "", "", "", "", ""],
    ["Contrato", "004880355431", "Cuenta relacionada", "0081-2714-17-0003177820", "", ""],
    ["MOVIMIENTOS DE CREDITO", "", "", "", "", ""],
    ["FECHA", "CONCEPTO", "LOCALIDAD", "SIT. MOV.", "IMPORTE", "EUR"],
    ["29/06", "JustEat", "MADRID", "AUT", "26,90", "EUR"],
    ["", "", "TOTAL OPERACIONES", "", "", ""],
    ["FECHA", "CONCEPTO", "LOCALIDAD", "SIT. MOV.", "IMPORTE", "EUR"],
    ["28/06", "Los Diamantes", "GRANADA", " ", "34,80", "EUR"],
]

PDF_TABLE: list[Page] = [
    [
        ["Fecha", "Concepto", "Importe"],
        ["11/07/2025\n12/07/2025", "Netflix.com\nOcio y cultura", "-19,99 €"],
        ["05/07/2025", "Recibo mes anterior", "270,74 €"],
    ],
    [
        ["Fecha", "Concepto", "Importe"],
        ["03/07/2025\n04/07/2025", "Www.dazn.com\nOcio y cultura", "-5,00 €"],
    ],
]

# A BBVA credit card statement. The date and the concept carry a second line, the table
# header is repeated on every page and the last row totals the statement.
BBVA_STATEMENT: list[Page] = [
    [
        ["Fecha", "Concepto", "Importe"],
        ["11/07/2025\n12/07/2025", "Netflix.com\nOcio y cultura", "-19,99 €"],
        ["09/07/2025\n10/07/2025", "Bonificacion pack viajes\nAbonos", "2,45 €"],
        ["05/07/2025\n05/07/2025", "Recibo mes anterior", "270,74 €"],
    ],
    [
        ["Fecha", "Concepto", "Importe"],
        ["03/07/2025\n04/07/2025", "Www.dazn.com\nOcio y cultura", "-5,00 €"],
        ["Total", "Importe total del periodo", "248,20 €"],
    ],
]

BBVA_LARGE_AMOUNT: list[Page] = [
    [
        ["Fecha", "Concepto", "Importe"],
        ["11/07/2025\n12/07/2025", "Viaje a Japon\nViajes", "-1.234,56 €"],
    ]
]

# The concept of the totals row is left blank, as a table that carries its own subtotals does
BBVA_BLANK_CELL: list[Page] = [
    [
        ["Fecha", "Concepto", "Importe"],
        ["11/07/2025\n12/07/2025", "Netflix.com\nOcio y cultura", "-19,99 €"],
        ["Total", "", "248,20 €"],
    ]
]


# Cobee cannot export transactions, so the input is the transactions page saved as HTML.
# html_text renders one line per block element, which is what the parser walks through.
COBEE_PAGE_HEADER = ["Cobee", "Mi cuenta", "Saldo disponible", "250,00 €"]

COBEE_TRANSACTIONS = [
    "Transacciones",
    "15 May 2025",
    "Restaurante Botin",
    "-34,80 €",
    "Mercadona",
    "-12,05 €",
    "Anulada",
    "2 May 2025",
    "Acumulación en tarjeta",
    "150,00 €",
    "Preautorizacion",
    "0,00 €",
    "Cafeteria Lolina",
    "-2,50 €",
]

# Sabadell writes the card details twice and only starts listing operations after the
# credit limit line.
SABADELL_TXT_HEADER = [
    "Contrato: 004880355431",
    "Cuenta relacionada: 0081-2714-17-0003177820",
    "Titular: NOMBRE APELLIDO",
    "",
    "FECHA|CONCEPTO|LOCALIDAD|SIT. MOV.|IMPORTE",
    "Límite de crédito: 2.000,00 EUR",
    "Límite autorizado: 0,00 EUR",
    "Forma pago mensual: Total del saldo gastado",
    "",
    "FECHA|CONCEPTO|LOCALIDAD|IMPORTE",
]

SABADELL_TXT_TRANSACTIONS = [
    "25/04|BARBERIA DOCKLANDS|MADRID|48,00EUR(2)",
    "22/04|JUSTEAT|MADRID|18,00EUR(1)",
    "20/04|DEVOLUCION COMPRA|MADRID|-12,50EUR",
    "19/04|VIAJE A JAPON|TOKIO|1.212,16EUR",
]


def cobee_export(lines: Iterable[str], header: Iterable[str] = COBEE_PAGE_HEADER) -> str:
    """Render a saved Cobee page whose transaction list is made of `lines`.

    The first line is the heading that opens the list, as on the real page. It is rendered
    as a heading element, which is what makes the extracted text carry blank lines.
    """
    heading, *entries = lines
    blocks = "\n".join(f"<div>{line}</div>" for line in [*header])
    entry_blocks = "\n".join(f"<div>{line}</div>" for line in entries)
    return (
        f"<html><body><div id='app'>{blocks}"
        f"<div id='list'><h2>{heading}</h2>{entry_blocks}</div></div></body></html>"
    )


def sabadell_statement(lines: Iterable[str], header: Iterable[str] = SABADELL_TXT_HEADER) -> str:
    return "\n".join([*header, *lines])


def write_xls(path: Path, rows: Iterable[Row]) -> Path:
    import pyexcel

    pyexcel.save_as(array=[list(row) for row in rows], dest_file_name=str(path))
    return path


def write_pdf(
    path: Path,
    pages: Sequence[Page],
    draw_grid: bool = True,
    open_borders: Iterable[tuple[int, int, int]] = (),
) -> Path:
    """Write a PDF where every page holds a single table.

    Args:
        path: file to write.
        pages: for each page, the rows of its table. A cell containing newlines is drawn
            as several lines of text inside the same cell.
        draw_grid: when False no line is stroked, so pdfplumber finds no table at all.
        open_borders: `(page, row, border)` triples naming a vertical border that is not
            drawn for that row. The two cells it separates merge, and pdfplumber reports
            the second one as `None`.
    """
    skipped = set(open_borders)
    contents = [
        _page_content(rows, draw_grid, {(r, b) for p, r, b in skipped if p == page_number})
        for page_number, rows in enumerate(pages)
    ]

    page_ids = [4 + index for index in range(len(pages))]
    content_ids = [4 + len(pages) + index for index in range(len(pages))]

    kids = b" ".join(b"%d 0 R" % page_id for page_id in page_ids)
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [%s] /Count %d >>" % (kids, len(pages)),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
        *(
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %d %d] "
            b"/Resources << /Font << /F1 3 0 R >> >> /Contents %d 0 R >>"
            % (PAGE_WIDTH, PAGE_HEIGHT, content_id)
            for content_id in content_ids
        ),
        *(b"<< /Length %d >>\nstream\n%s\nendstream" % (len(c), c) for c in contents),
    ]

    document = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(document))
        document += b"%d 0 obj\n" % number + body + b"\nendobj\n"

    xref_offset = len(document)
    document += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    document += b"".join(b"%010d 00000 n \n" % offset for offset in offsets)
    document += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1,
        xref_offset,
    )

    path.write_bytes(bytes(document))
    return path


def _page_content(rows: Page, draw_grid: bool, open_borders: set[tuple[int, int]]) -> bytes:
    columns = max(len(row) for row in rows)
    xs = [LEFT + index * COLUMN_WIDTH for index in range(columns + 1)]

    ys = [TOP]
    for row in rows:
        lines = max(len(cell.splitlines()) for cell in row) or 1
        ys.append(ys[-1] - (LINE_HEIGHT * lines + ROW_PADDING))

    parts = [b"0.5 w"]
    if draw_grid:
        for border, x in enumerate(xs):
            parts += [
                b"%d %d m %d %d l S" % (x, ys[row], x, ys[row + 1])
                for row in range(len(rows))
                if (row, border) not in open_borders
            ]
        parts += [b"%d %d m %d %d l S" % (xs[0], y, xs[-1], y) for y in ys]

    for row_number, row in enumerate(rows):
        for column, cell in enumerate(row):
            for line_number, line in enumerate(cell.splitlines()):
                parts.append(
                    b"BT /F1 %d Tf %d %d Td (%s) Tj ET"
                    % (
                        FONT_SIZE,
                        xs[column] + 3,
                        ys[row_number] - LINE_HEIGHT * (line_number + 1),
                        _pdf_string(line),
                    )
                )

    return b"\n".join(parts)


def _pdf_string(text: str) -> bytes:
    out = bytearray()
    for character in text:
        if character in "()\\":
            out += b"\\"
        out += character.encode("cp1252", errors="replace")
    return bytes(out)


def main() -> None:
    (ASSETS / "parsers").mkdir(parents=True, exist_ok=True)
    write_xls(ASSETS / "parsers/statement.xls", XLS_SHEET)
    write_pdf(ASSETS / "parsers/statement.pdf", PDF_TABLE)
    write_pdf(ASSETS / "parsers/no_table.pdf", PDF_TABLE, draw_grid=False)
    write_pdf(ASSETS / "parsers/merged_cell.pdf", PDF_TABLE[:1], open_borders=[(0, 2, 2)])

    write_pdf(ASSETS / "bbva/bbva.pdf", BBVA_STATEMENT)
    write_pdf(ASSETS / "bbva/bbva_large_amount.pdf", BBVA_LARGE_AMOUNT)
    write_pdf(ASSETS / "bbva/bbva_blank_cell.pdf", BBVA_BLANK_CELL)

    (ASSETS / "sabadell").mkdir(parents=True, exist_ok=True)
    write_xls(ASSETS / "sabadell/movements.xls", SABADELL_SHEET)
    # The two last rows are the debit section, a card that has none ends with the legend
    write_xls(ASSETS / "sabadell/movements_without_debit.xls", SABADELL_SHEET[:-2])
    # Sabadell exports its txt statement in the Windows Spanish code page
    (ASSETS / "sabadell/movements.txt").write_text(
        sabadell_statement(SABADELL_TXT_TRANSACTIONS), encoding="cp1252"
    )

    (ASSETS / "cobee").mkdir(parents=True, exist_ok=True)
    (ASSETS / "cobee/transactions.html").write_text(
        cobee_export(COBEE_TRANSACTIONS), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
