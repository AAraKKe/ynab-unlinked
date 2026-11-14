from enum import StrEnum
from typing import Annotated

import typer

from ynab_unlinked import keychain
from ynab_unlinked.cli.display import (
    bullet_list,
    confirm,
    console,
    info,
    question,
    success,
    warning,
)
from ynab_unlinked.cli.setup import ensure_config
from ynab_unlinked.cli.utils import prompt_for_api_key, prompt_for_budget
from ynab_unlinked.config import ImportedFiles, LatestConfig, switch_budget, update_config
from ynab_unlinked.local_data import delete_local_data, local_data_paths
from ynab_unlinked.privacy import privacy_notice


class ValidKeys(StrEnum):
    BUDGET = "budget"
    API_KEY = "api_key"
    IMPORTED_FILES = "imported_files"


config_app = typer.Typer(help="Manage YNAB Unlinked configuration")


@config_app.command(name="set")
def set_command(
    context: typer.Context,
    key: Annotated[ValidKeys, typer.Argument(help="The config key to set", show_default=False)],
):
    """Set configuration options"""
    ctx = ensure_config(context, require_token=key is ValidKeys.BUDGET)
    config: LatestConfig = ctx.config

    match key:
        case ValidKeys.API_KEY:
            privacy_notice()
            api_key = prompt_for_api_key()
            config.api_key = api_key
            update_config(lambda saved: setattr(saved, "api_key", api_key))
            success("🎉 The API key has been updated")
        case ValidKeys.BUDGET:
            budget = prompt_for_budget(config.api_key)
            if budget.id != config.budget.id:
                warning(
                    "Bank accounts, account settings, debt mappings and the last "
                    "reconciliation belong to the old budget, so they are cleared."
                )
            switch_budget(config, budget)
            update_config(lambda saved: switch_budget(saved, budget))
            success("🎉 The budget has been updated")
        case ValidKeys.IMPORTED_FILES:
            info(
                "What yul does with the statement files once they are imported: `ask` each "
                "time, `remove` them from this computer for good, or `keep` them."
            )
            choice = ImportedFiles(
                question(
                    "Imported files",
                    choices=[option.value for option in ImportedFiles],
                    default=config.imported_files.value,
                )
            )
            update_config(lambda saved: setattr(saved, "imported_files", choice))
            success(f"🎉 Imported files: {choice.value}")


@config_app.command(name="show")
def show(context: typer.Context):
    ctx = ensure_config(context)
    config: LatestConfig = ctx.config
    shown = config.model_copy(update={"api_key": keychain.mask_token(config.api_key)})
    console().print(shown.model_dump_json(indent=2))


@config_app.command(name="reset")
def reset_command(
    yes: Annotated[
        bool,
        typer.Option("--yes", "-y", help="Skip the confirmation prompt."),
    ] = False,
):
    """Delete all locally stored YNAB Unlinked data, including your YNAB API key."""
    paths_to_remove = local_data_paths()

    if not paths_to_remove:
        info("No YNAB Unlinked data was found on this machine. Nothing to delete.")
        return

    info("The following will be permanently deleted:")
    info(bullet_list(str(p) for p in paths_to_remove))
    if (name := keychain.backend_name()) is not None:
        info(f"Your YNAB token is removed from the {name} too.")
    warning(
        "This will remove your YNAB API key, selected budget, entity accounts and the local "
        "copy of your YNAB transactions."
    )

    if not yes and not confirm("Are you sure you want to continue?", default=False):
        info("Aborted. Nothing was deleted.")
        return

    delete_local_data(paths_to_remove)

    success("🧹 All locally stored YNAB Unlinked data has been deleted.")
