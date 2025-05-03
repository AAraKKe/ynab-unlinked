import typer

from ynab_unlinked.config import Config, ensure_config
from ynab_unlinked.context_object import YnabUnlinkedContext
from ynab_unlinked.commands import load, config
from ynab_unlinked.display import prompt_for_api_key, prompt_for_budget

app = typer.Typer()

app.add_typer(load, name="load")
app.add_typer(config, name="config")


@app.command(name="setup")
def setup_command():
    """Setup YNAB Unlinked"""
    print("[bold]Welcome to ynab-unlinked! Lets setup your connection")
    api_key = prompt_for_api_key()
    config = Config(api_key=api_key, budget_id="")
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

    if not ensure_config():
        setup_command()
    config = Config.load()
    context.obj = YnabUnlinkedContext(config=config, extras=None)


def main():
    app(prog_name="yul")


if __name__ == "__main__":
    main()
