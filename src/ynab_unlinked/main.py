from typing import Final, cast

import typer

from ynab_unlinked import app
from ynab_unlinked.commands import config_app, load
from ynab_unlinked.config import Config, ConfigV1, ConfigV2, get_config
from ynab_unlinked.config.core import ConfigError
from ynab_unlinked.context_object import YnabUnlinkedContext
from ynab_unlinked.display import bold, success
from ynab_unlinked.formatter import Formatter
from ynab_unlinked.utils import prompt_for_api_key, prompt_for_budget

app.add_typer(load, name="load")
app.add_typer(config_app, name="config")

VERSION_MAPPING: Final[dict[str, type[Config]]] = {
    "V1": ConfigV1,
    "V2": ConfigV2,
}


@app.command(name="setup")
def setup_command():
    """Setup YNAB Unlinked"""
    bold("Welcome to ynab-unlinked! Lets setup your connection")
    api_key = prompt_for_api_key()
    budget = prompt_for_budget(api_key)
    config = ConfigV2(api_key=api_key, budget=budget)
    config.save()

    success("All done!")


@app.callback(no_args_is_help=True)
def cli(context: typer.Context):
    """
    Create transations in your YNAB account from a bank export of your extract.
    \n

    The first time the command is run you will be asked some questions to setup your YNAB connection. After that,
    transaction processing won't require any input unless there are some actions to take for specific transactions.
    """

    if context.invoked_subcommand == "setup":
        # If we are running setup there is nothing to do here
        return

    # Load the proper config or run setup to create it
    config = get_config()
    if config is None:
        setup_command()
        config = get_config()

    if config is None:
        raise ConfigError("Unexpected error: config could not be loaded")

    context.obj = YnabUnlinkedContext(
        config=cast(ConfigV2, config),
        extras=None,
        formatter=Formatter(
            date_format=config.budget.date_format,
            currency_format=config.budget.currency_format,
        ),
    )


def main():
    app(prog_name="yul")
