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


def question(
    message: str,
    *,
    password: bool = False,
    choices: list[str] | None = None,
    show_choices: bool = True,
    default: str | None = None,
) -> str:
    """Ask for a line of text, one of `choices` when given. `default` answers an empty line."""
    prompt = f"[bold cyan]{message}[/bold cyan]"
    if default is None:
        return Prompt.ask(
            prompt,
            console=console(),
            password=password,
            choices=choices,
            show_choices=show_choices,
        )
    return Prompt.ask(
        prompt,
        console=console(),
        password=password,
        choices=choices,
        show_choices=show_choices,
        default=default,
    )


def confirm(message: str, *, default: bool | None = None) -> bool:
    """Ask a yes or no question. Without a `default`, it asks until it gets an answer."""
    prompt = f"[bold cyan]{message}[/bold cyan]"
    if default is None:
        return Confirm.ask(prompt, console=console())
    return Confirm.ask(prompt, console=console(), default=default)


def bullet_list(items: Iterable[str]) -> str:
    return "\n".join(f" • {item}" for item in items)
