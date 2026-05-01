import shutil
from enum import StrEnum
from pathlib import Path
from typing import Annotated, assert_never

import typer

from ynab_unlinked.config import ConfigV2
from ynab_unlinked.config.paths import config_path, v1_config_path
from ynab_unlinked.display import bullet_list, confirm, console, info, success, warning
from ynab_unlinked.privacy import privacy_notice
from ynab_unlinked.setup import ensure_config
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
    ctx = ensure_config(context)
    config: ConfigV2 = ctx.config

    match key:
        case ValidKeys.API_KEY:
            privacy_notice()
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
    ctx = ensure_config(context)
    config: ConfigV2 = ctx.config
    console().print(config.model_dump_json(indent=2))


@config_app.command(name="reset")
def reset_command(
    yes: Annotated[
        bool,
        typer.Option("--yes", "-y", help="Skip the confirmation prompt."),
    ] = False,
):
    """Delete all locally stored YNAB Unlinked data, including your YNAB API key."""
    paths_to_remove: list[Path] = []

    v2_dir = config_path().parent
    if v2_dir.is_dir():
        paths_to_remove.append(v2_dir)

    v1_path = v1_config_path()
    if v1_path.is_file() and v1_path.parent not in paths_to_remove:
        paths_to_remove.append(v1_path.parent)

    if not paths_to_remove:
        info("No YNAB Unlinked data was found on this machine. Nothing to delete.")
        return

    info("The following directories will be permanently deleted:")
    info(bullet_list(str(p) for p in paths_to_remove))
    warning(
        "This will remove your YNAB API key, selected budget, payee rules, and entity checkpoints."
    )

    if not yes and not confirm("Are you sure you want to continue?", default=False):
        info("Aborted. Nothing was deleted.")
        return

    for path in paths_to_remove:
        shutil.rmtree(path)

    success("🧹 All locally stored YNAB Unlinked data has been deleted.")
