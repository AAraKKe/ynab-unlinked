from enum import StrEnum
from typing import Annotated, assert_never

import typer

from ynab_unlinked.config import ConfigV2
from ynab_unlinked.context_object import YnabUnlinkedContext
from ynab_unlinked.display import console, success
from ynab_unlinked.utils import prompt_for_api_key, prompt_for_budget


class ValidKeys(StrEnum):
    BUDGET = "budget"
    API_KEY = "api_key"


config_app = typer.Typer(help="Manage YNAB Unlinked configuration")


@config_app.command(name="set")
def set_command(
    context: typer.Context,
    key: Annotated[ValidKeys, typer.Argument(help="The config key to set", show_default=False)],
):
    """Set configuration options"""
    ctx: YnabUnlinkedContext = context.obj
    config: ConfigV2 = ctx.config

    match key:
        case ValidKeys.API_KEY:
            api_key = prompt_for_api_key()
            config.api_key = api_key
            config.save()
            success("🎉 The API key has been updated")
        case ValidKeys.BUDGET:
            budget = prompt_for_budget(config.api_key)
            config.budget = budget
            config.save()
            success("🎉 The budget has been updated")
        case never:
            assert_never(never)


@config_app.command(name="show")
def show(context: typer.Context):
    ctx: YnabUnlinkedContext = context.obj
    config: ConfigV2 = ctx.config
    console().print(config.model_dump_json(indent=2))
