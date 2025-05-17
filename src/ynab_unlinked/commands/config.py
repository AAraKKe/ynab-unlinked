from typing_extensions import Annotated
from typing import assert_never
from enum import StrEnum

import typer
from rich import print

from ynab_unlinked.config import Config, ensure_config
from ynab_unlinked.display import prompt_for_api_key, prompt_for_budget


class ValidKeys(StrEnum):
    BUDGET = "budget"
    API_KEY = "api_key"


config = typer.Typer(help="Manage YNAB Unlinked configuration")


@config.command(name="set")
def set_command(
    key: Annotated[
        ValidKeys, typer.Argument(help="The config key to set", show_default=False)
    ],
):
    """Set configuration options"""

    match key:
        case ValidKeys.API_KEY:
            api_key = prompt_for_api_key()
            # If the config exist, just update it
            if ensure_config():
                config = Config.load()
                config.api_key = api_key
            else:
                config = Config(api_key=api_key, budget_id="")

            config.save()
            print("[bold green]🎉 The API key has been updated[/]")
        case ValidKeys.BUDGET:
            budget_id = prompt_for_budget()
            config = Config.load()
            config.budget_id = budget_id
            config.save()
            print("[bold green]🎉 The budget has been updated[/]")
        case never:
            assert_never(never)


@config.command(name="show")
def show():
    if not ensure_config():
        raise typer.Abort(
            "YNAB Unlinked config not found. Run 'yul setup' to configure it."
        )

    config = Config.load()
    print(config.model_dump_json(indent=2))
