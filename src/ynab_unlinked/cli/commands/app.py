from typing import Annotated

import typer
from rich.markup import escape

from ynab_unlinked import web
from ynab_unlinked.cli.display import error, info

INSTALL_HINT = (
    "Install the web UI with: uv tool install 'ynab-unlinked[web]'\n"
    "or, with pip: pip install 'ynab-unlinked[web]'"
)


def app_command(
    port: Annotated[
        int | None,
        typer.Option("--port", help="Port to listen on. A free one is picked by default."),
    ] = None,
    no_browser: Annotated[
        bool,
        typer.Option("--no-browser", help="Do not open the browser, only print the link."),
    ] = False,
):
    """Open the yul web app in your browser. It runs only on this computer."""
    if not web.available():
        error("The web UI is not installed.")
        info(escape(INSTALL_HINT))
        raise typer.Exit(1)

    from ynab_unlinked.web import app as web_app

    web_app.run(port=port, open_browser=not no_browser, announce=info)
