import typer
from rich import print

from ynab_unlinked import app
from ynab_unlinked.commands import config, load
from ynab_unlinked.config import ConfigV1, v1_config_path
from ynab_unlinked.context_object import YnabUnlinkedContext
from ynab_unlinked.display import prompt_for_api_key, prompt_for_budget

app.add_typer(load, name="load")
app.add_typer(config, name="config")


@app.command(name="setup")
def setup_command():
    """Setup YNAB Unlinked"""
    print("[bold]Welcome to ynab-unlinked! Lets setup your connection")
    api_key = prompt_for_api_key()
    config = ConfigV1(api_key=api_key, budget_id="")
    config.save()

    budget_id = prompt_for_budget()
    config.budget_id = budget_id
    config.save()

    print("[bold green]All done!")


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

    if not v1_config_path().exists():
        setup_command()
    config = ConfigV1.load()
    context.obj = YnabUnlinkedContext(config=config, extras=None)


def main():
    app(prog_name="yul")


if __name__ == "__main__":
    main()
