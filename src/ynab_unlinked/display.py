from __future__ import annotations

from collections.abc import Iterable
from contextlib import contextmanager
from typing import TYPE_CHECKING

from rich.console import Console
from rich.prompt import Confirm, Prompt
from rich.status import Status

__console: Console | None = None


if TYPE_CHECKING:
    from questionary import Choice


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


def _prepare_choices[T](
    choices: dict[T, str], default: T | None = None
) -> tuple[list[Choice], Choice | None]:
    from questionary import Choice

    to_return = []
    initial_choice = None
    for value, title in choices.items():
        checked = False
        if default and default == value:
            checked = True

        choice = Choice(title, value=value, checked=checked)
        if checked:
            initial_choice = choice

        to_return.append(choice)
    return to_return, initial_choice


def select[T](question: str, choices: dict[T, str], default: T | None = None) -> T:
    import questionary

    _choices, _ = _prepare_choices(choices, default)

    return questionary.select(message=question, choices=_choices).ask()


def checkboxes[T](question: str, choices: dict[T, str], default: T | None = None) -> list[T]:
    import questionary

    _choices, initial_choice = _prepare_choices(choices, default)

    return questionary.checkbox(
        message=question, choices=_choices, initial_choice=initial_choice
    ).ask()
