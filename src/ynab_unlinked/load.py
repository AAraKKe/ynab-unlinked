import pkgutil
import importlib

import typer

from ynab_unlinked import entities

load = typer.Typer(
    help="Load transactions from a bank statement into your YNAB account.",
)


# Dynamically load all entities commands when present
for finder, name, ispkg in pkgutil.iter_modules(entities.__path__):
    if not ispkg:
        continue

    module = importlib.import_module(f"{entities.__name__}.{name}")
    if not hasattr(module, "command"):
        continue

    command = getattr(module, "command")

    if callable(command):
        load.command(name=name, no_args_is_help=True)(command)
