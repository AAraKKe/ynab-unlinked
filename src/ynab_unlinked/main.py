from typing import Final

import typer

from ynab_unlinked import app
from ynab_unlinked.commands import config_app, load, privacy_command
from ynab_unlinked.config import Config, ConfigV1, ConfigV2
from ynab_unlinked.setup import load_context, run_setup

app.add_typer(load, name="load")
app.add_typer(config_app, name="config")
app.command(name="privacy")(privacy_command)

VERSION_MAPPING: Final[dict[str, type[Config]]] = {
    "V1": ConfigV1,
    "V2": ConfigV2,
}


@app.command(name="setup")
def setup_command():
    """Setup YNAB Unlinked"""
    run_setup()


@app.callback(no_args_is_help=True)
def cli(context: typer.Context):
    """
    Create transations in your YNAB account from a bank export of your extract.
    \n

    The first time the command is run you will be asked some questions to setup your YNAB connection. After that,
    transaction processing won't require any input unless there are some actions to take for specific transactions.
    """
    # Load the persisted config when one exists. Commands that need a
    # config call ``ensure_config`` to either pick it up here or prompt
    # setup. Commands that don't (``setup``, ``privacy``, ``config reset``)
    # simply ignore ``context.obj``.
    context.obj = load_context()


def main():
    app(prog_name="yul")
