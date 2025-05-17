import importlib
import pkgutil
from typing import Annotated

import typer

from ynab_unlinked import entities
from ynab_unlinked.context_object import YnabUnlinkedContext

load = typer.Typer(
    help="Load transactions from a bank statement into your YNAB account.",
)


@load.callback()
def load_callback(
    context: typer.Context,
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
    obj: YnabUnlinkedContext = context.obj

    obj.show = show
    obj.reconcile = reconcile


# Dynamically load all entities commands when present
for _finder, name, ispkg in pkgutil.iter_modules(entities.__path__):
    if not ispkg:
        continue

    module = importlib.import_module(f"{entities.__name__}.{name}")
    if not hasattr(module, "command"):
        continue

    command = module.command

    if callable(command):
        load.command(name=name, no_args_is_help=True)(command)
