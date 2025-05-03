import typer
from rich import print
from rich.prompt import Prompt
from rich.status import Status

from ynab_unlinked.config import Config, ensure_config
from ynab_unlinked.context_object import YnabUnlinkedContext
from ynab_unlinked.commands import load, config
from ynab_unlinked.ynab_api.client import Client

app = typer.Typer()

app.add_typer(load, name="load")
app.add_typer(config, name="config")


def prompt_for_config():
    print("[bold]Welcome to ynab-unlinked! Lets setup your connection")
    api_key = Prompt.ask("What is the API Key to connect to YNAB?", password=True)
    client = Client(Config(api_key=api_key, budget_id="", entities={}))

    with Status("Getting budgets..."):
        budgets = client.budgets()

    print("Available budgets:")
    for idx, budget in enumerate(budgets):
        print(f" - {idx + 1}. {budget.name}")

    budget_num = Prompt.ask(
        "What budget do you want to use? (By number)",
        choices=[str(i) for i in range(1, len(budgets) + 1)],
        show_choices=False,
    )
    budget = budgets[int(budget_num) - 1]

    print(f"[bold]Selected budget: {budget.name}")

    config = Config(api_key=api_key, budget_id=budget.id, entities={})
    config.save()

    print("[bold green]All done!")
    return config


@app.callback(no_args_is_help=True)
def cli(context: typer.Context):
    """
    Create transations in your YNAB account from a bank export of your extract.
    \n

    The first time the command is run you will be asked some questions to setup your YNAB connection. After that,
    transaction processing won't require any input unless there are some actions to take for specific transactions.
    """

    config = Config.load() if ensure_config() else prompt_for_config()
    context.obj = YnabUnlinkedContext(config=config, extras=None)


def main():
    app(prog_name="yul")


if __name__ == "__main__":
    main()
