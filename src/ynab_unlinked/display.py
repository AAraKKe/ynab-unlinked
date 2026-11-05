from __future__ import annotations

from collections.abc import Iterable
from contextlib import ExitStack, contextmanager
from types import TracebackType

from rich.console import Console
from rich.prompt import Confirm, Prompt
from rich.status import Status

__console: Console | None = None


def console() -> Console:
    global __console
    if __console is None:
        __console = Console()
    return __console


def success(message: str):
    console().print(f"[bold green]{message}[/bold green]")


def error(message: str):
    console().print(f"[bold red]{message}[/bold red]")


def warning(message: str):
    console().print(f"[bold orange1]{message}[/bold orange1]")


def info(message: str):
    console().print(message)


def bold(message: str):
    return console().print(f"[bold]{message}[/bold]")


@contextmanager
def process(message: str, completed_message: str | None = None):
    with Status(message, spinner="dots"):
        yield
    if completed_message:
        success(completed_message)


class CliProgress:
    """Shows the steps of a core call as a spinner per step on the terminal.

    Use it as a context manager so the spinner stops even when the call raises.
    """

    def __init__(self) -> None:
        self._step = ExitStack()

    def __enter__(self) -> CliProgress:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self._step.close()

    def start(self, message: str) -> None:
        self._step.close()
        self._step.enter_context(process(message))

    def done(self, message: str | None = None) -> None:
        self._step.close()
        if message:
            success(f"✔ {message}")

    def info(self, message: str) -> None:
        info(message)

    def warn(self, message: str) -> None:
        warning(message)


def question(message: str, **kwargs) -> str:
    return Prompt.ask(f"[bold cyan]{message}[/bold cyan]", console=console(), **kwargs)


def confirm(message: str, **kwargs) -> bool:
    return Confirm.ask(f"[bold cyan]{message}[/bold cyan]", console=console(), **kwargs)


def bullet_list(items: Iterable[str]) -> str:
    return "\n".join(f" • {item}" for item in items)
