from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Annotated

import typer


def command(
    context: typer.Context,
    input_file: Annotated[
        Path,
        typer.Argument(exists=True, file_okay=True, dir_okay=False, readable=True),
    ],
    year: Annotated[
        int | None,
        typer.Option(
            "-y",
            "--year",
            help=(
                "Year of the transactions to import. Sabadell statements do not include the year in the date, "
                "so you need to specify it. If not specified, the current year will be used."
            ),
        ),
    ] = None,
):
    """
    Inputs transactions from a Sabadell TXT or XLS file.

    From your Sabadell Credit Card statement, you can download a txt file with the transactions.
    At the moment only txt format is supported.
    """

    from ynab_unlinked.context_object import YnabUnlinkedContext
    from ynab_unlinked.process import process_transactions

    from .sabadell import SabadellParser

    ctx: YnabUnlinkedContext = context.obj

    year = dt.date.today().year if year is None else year

    process_transactions(
        entity=SabadellParser(year=year),
        input_file=input_file,
        context=ctx,
    )
