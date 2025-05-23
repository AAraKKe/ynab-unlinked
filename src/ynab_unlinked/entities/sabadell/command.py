from pathlib import Path
from typing import Annotated

import typer

from ynab_unlinked.context_object import YnabUnlinkedContext
from ynab_unlinked.process import process_transactions


def command(
    context: typer.Context,
    input_file: Annotated[
        Path,
        typer.Argument(exists=True, file_okay=True, dir_okay=False, readable=True),
    ],
):
    """
    Inputs transactions from a Sabadell txt file.

    From your Sabadell Credit Card statement, you can download a txt file with the transactions.
    At the moment only txt format is supported.
    """
    from .sabadell import SabadellParser

    ctx: YnabUnlinkedContext = context.obj

    process_transactions(
        entity=SabadellParser(),
        input_file=input_file,
        context=ctx,
    )
