from pathlib import Path
from typing import Annotated

import typer

from ynab_unlinked.context_object import YnabUnlinkedContext
from ynab_unlinked.process import process_transactions

from .cobee import Cobee, CobeeContext, Language


def command(
    context: typer.Context,
    input_file: Annotated[
        Path,
        typer.Argument(exists=True, file_okay=True, dir_okay=False, readable=True),
    ],
    language: Annotated[
        Language,
        typer.Option(
            "-l",
            "--lang",
            help="Language used when exporting the HTML webisite",
        ),
    ] = Language.ES,
):
    """
    Import transactions from a Cobee HTML file.

    Cobee that not support exporting transactions. To use the Cobee entity, form the website,
    find the list of transactions of the month you want to import into YNAB and save the page as HTML.

    You cando this by Right Click > Save as, and select where you want to save the file.
    """

    ctx: YnabUnlinkedContext[CobeeContext] = context.obj
    ctx.extras = CobeeContext(language=language)

    process_transactions(
        entity=Cobee(),
        input_file=input_file,
        context=ctx,
    )
