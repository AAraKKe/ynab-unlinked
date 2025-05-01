from pathlib import Path

import typer
from typing_extensions import Annotated

from ynab_unlinked.context_object import YnabUnlinkedCommandObject
from ynab_unlinked.process import process_transactions


def command(
    context: typer.Context,
    input_file: Annotated[
        Path,
        typer.Argument(exists=True, file_okay=True, dir_okay=False, readable=True),
    ],
    show: Annotated[
        bool,
        typer.Option(
            "-s",
            "--show",
            help="Just show the transactions available in the input file.",
        ),
    ] = False,
    reconcile: Annotated[
        bool, typer.Option("-r", "--reconcile", help="Reconcile cleared transactions")
    ] = False,
):
    """
    Inputs transactions from a Sabadell txt file.

    From your Sabadell Credit Card statement, you can download a txt file with the transactions.
    At the moment only txt format is supported.
    """
    from .sabadell import SabadellParser

    ctx: YnabUnlinkedCommandObject = context.obj

    parser = SabadellParser()
    transactions = parser.parse(input_file, ctx.config)
    ctx.transactions = transactions

    process_transactions(
        parsed_input=transactions,
        config=ctx.config,
        show=show,
        reconcile=reconcile,
    )
