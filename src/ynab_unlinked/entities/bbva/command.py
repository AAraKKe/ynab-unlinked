from pathlib import Path
from typing import Annotated

import typer

from .bbva import BBVA


def command(
    context: typer.Context,
    input_file: Annotated[
        Path,
        typer.Argument(exists=True, file_okay=True, dir_okay=False, readable=True),
    ],
):
    """
    Import transactions from BBVA using a Credit Card PDF report.
    """
    from ynab_unlinked.context_object import YnabUnlinkedContext
    from ynab_unlinked.process import process_transactions

    ctx: YnabUnlinkedContext = context.obj

    process_transactions(
        BBVA(),
        input_file,
        ctx,
    )
