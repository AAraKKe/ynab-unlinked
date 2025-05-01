import typer

from ynab_unlinked.entities import sabadell

load = typer.Typer(
    help="Load transactions from a bank statement into your YNAB account.",
)

COMMANDS = {
    "sabadell": sabadell.command,
}

# Load all entity commands
for name, command in COMMANDS.items():
    load.command(name=name)(command)
