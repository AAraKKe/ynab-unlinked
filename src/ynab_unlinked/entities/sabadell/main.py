from pathlib import Path

import typer
from typing_extensions import Annotated

from ynab_unlinked.context_object import YnabUnlinkedCommandObject
from ynab_unlinked.process import process_transactions
from ynab_unlinked import app


@app.command(no_args_is_help=True)
def sabadell(
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
    Parse a Sabadell txt input file.
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
