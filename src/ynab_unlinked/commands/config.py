from enum import StrEnum
from typing import Annotated, assert_never

import typer
from rich import print

from ynab_unlinked.config import ConfigV1, v1_config_path
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
            if v1_config_path().exists():
                config = ConfigV1.load()
                config.api_key = api_key
            else:
                config = ConfigV1(api_key=api_key, budget_id="")

            config.save()
            print("[bold green]🎉 The API key has been updated[/]")
        case ValidKeys.BUDGET:
            budget_id = prompt_for_budget()
            config = ConfigV1.load()
            config.budget_id = budget_id
            config.save()
            print("[bold green]🎉 The budget has been updated[/]")
        case never:
            assert_never(never)


@config.command(name="show")
def show():
    if not v1_config_path().exists():
        raise typer.Abort(
            "YNAB Unlinked config not found. Run 'yul setup' to configure it."
        )

    config = ConfigV1.load()
    print(config.model_dump_json(indent=2))
