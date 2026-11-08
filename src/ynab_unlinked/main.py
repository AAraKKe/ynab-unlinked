from typing import Annotated

import typer

from ynab_unlinked import web
from ynab_unlinked.cli import app
from ynab_unlinked.cli.commands import config_app, load, privacy_command
from ynab_unlinked.cli.commands.app import app_command
from ynab_unlinked.cli.display import confirm, info, warning
from ynab_unlinked.cli.setup import config_exists, run_setup

app.add_typer(load, name="load")
app.add_typer(config_app, name="config")
app.command(name="privacy")(privacy_command)
# Without the `web` extra the command stays out of --help and only explains how to install it
app.command(name="app", hidden=not web.available())(app_command)


@app.command(name="setup")
def setup_command(
    yes: Annotated[
        bool,
        typer.Option("--yes", "-y", help="Replace an existing config without asking."),
    ] = False,
):
    """Setup YNAB Unlinked"""
    if not yes and config_exists():
        warning(
            "yul is already set up. Setting it up again replaces the config: the token, the "
            "budget, the bank accounts, the account settings and the debt mappings."
        )
        if not confirm("Replace the current config?", default=False):
            info("Nothing changed. `yul config set` changes the token or the budget alone.")
            return
    run_setup()


@app.callback(no_args_is_help=True)
def cli(context: typer.Context):
    """
    Create transations in your YNAB account from a bank export of your extract.
    \n

    The first time the command is run you will be asked some questions to setup your YNAB connection. After that,
    transaction processing won't require any input unless there are some actions to take for specific transactions.
    """
    # Nothing is loaded here: the commands that need the config call ``ensure_config``, so
    # ``setup``, ``privacy`` and ``config reset`` never read it (nor the keychain) and keep
    # working when the file is broken.


def main():
    app(prog_name="yul")
