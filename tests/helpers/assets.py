from collections.abc import Generator, Sequence
from pathlib import Path
from typing import Any

ASSETS_PATH = Path(__file__).parents[1] / "assets"
AssetPath = Path | str


def path(asset_path: AssetPath) -> Path:
    return ASSETS_PATH / asset_path


def read_text(asset_path: AssetPath, encoding="utf-8") -> str:
    return path(asset_path).read_text(encoding=encoding)


def read_lines(asset_path: AssetPath, encoding="utf-8") -> Generator[str]:
    with open(path(asset_path), encoding=encoding) as asset_file:
        yield from asset_file


def read_pdf(
    asset_path: AssetPath,
    allow_empty_columns: bool = False,
    table_settings: dict[str, Any] | None = None,
    expected_number_of_columns: int | None = None,
) -> Generator[Sequence[str]]:
    from ynab_unlinked.parsers import pdf

    yield from pdf(
        path(asset_path),
        allow_empty_columns=allow_empty_columns,  # type: ignore since we do not want to overload this method
        table_settings=table_settings,
        expected_number_of_columns=expected_number_of_columns,
    )


def read_xls(
    asset_path: AssetPath,
    read_after_row: int = 0,
    read_after_row_like: Sequence[str] | None = None,
) -> Generator[Sequence[str]]:
    from ynab_unlinked.parsers import xls

    yield from xls(
        path(asset_path),
        read_after_row=read_after_row,
        read_after_row_like=read_after_row_like,
    )
