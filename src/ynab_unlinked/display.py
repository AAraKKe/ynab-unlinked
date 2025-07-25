from __future__ import annotations

from collections.abc import Iterable
from contextlib import contextmanager

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


def question(message: str, **kwargs) -> str:
    return Prompt.ask(f"[bold cyan]{message}[/bold cyan]", console=console(), **kwargs)


def confirm(message: str, **kwargs) -> bool:
    return Confirm.ask(f"[bold cyan]{message}[/bold cyan]", console=console(), **kwargs)


def bullet_list(items: Iterable[str]) -> str:
    return "\n".join(f" • {item}" for item in items)
