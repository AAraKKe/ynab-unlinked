"""The `yul` command line: Typer commands, Rich output and the prompts.

Everything that only the terminal uses lives here. Nothing outside this package imports it
except `ynab_unlinked.main`, the entry point, and the CLI-side writers `activity` and
`privacy` that print through `display`.
"""

import typer

from ynab_unlinked.cli.cli_errors import YulGroup

app = typer.Typer(no_args_is_help=True, cls=YulGroup)
