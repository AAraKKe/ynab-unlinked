"""What every entity package offers as a loader, discovered at runtime.

Each entity package exposes a module level `spec: LoaderSpec`. Frontends list them with
`loaders()`, show their options, and build the entity with concrete option values:
`yul load <key>` is generated from the spec (`cli/commands/load.py`), its options from
`spec.options`, so adding a bank is one spec and one parser.
"""

from __future__ import annotations

import importlib
import pkgutil
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from ynab_unlinked.entities import Entity, InputType

AUTO = "auto"
"""Option value meaning "infer it from the file". `core.detect` resolves it before `build`."""


@dataclass(frozen=True)
class LoaderOption:
    key: str
    label: str
    default: str
    choices: tuple[str, ...] | None = None
    flags: tuple[str, ...] = ()
    """Its names on `yul load <key>`. Empty is `--<key>`."""
    help: str = ""
    """Its help on `yul load <key>`. Empty is the label."""
    integer: bool = False
    """The command line only takes a whole number (a year)."""

    @property
    def cli_flags(self) -> tuple[str, ...]:
        return self.flags or (f"--{self.key}",)


@dataclass(frozen=True)
class LoaderSpec:
    key: str
    """Package name: "bbva", "sabadell", "cobee"."""
    name: str
    """`Entity.name()`, the key the account is saved under in the config."""
    title: str
    """User facing name."""
    input_types: tuple[InputType, ...]
    options: tuple[LoaderOption, ...]
    build: Callable[[Mapping[str, str]], Entity]
    """Options to entity instance, every option bound. Raises `ValueError` on a missing,
    `auto` or invalid value."""
    help: str = ""
    """The help of `yul load <key>`."""

    def accepts(self, input_file: Path) -> bool:
        from ynab_unlinked.entities._sniff import suffix

        return suffix(input_file) in self.input_types


def concrete(options: Mapping[str, str], key: str) -> str:
    """The value of option `key`, which must have been resolved already."""
    value = options.get(key, AUTO)
    if value == AUTO:
        raise ValueError(f"The {key!r} option must be resolved before building the loader")
    return value


def loaders() -> list[LoaderSpec]:
    """Every loader shipped in `ynab_unlinked.entities`, sorted by key."""
    from ynab_unlinked import entities

    specs: list[LoaderSpec] = []
    for _finder, name, ispkg in pkgutil.iter_modules(entities.__path__):
        if not ispkg:
            continue

        module = importlib.import_module(f"{entities.__name__}.{name}")
        if isinstance(spec := getattr(module, "spec", None), LoaderSpec):
            specs.append(spec)

    return sorted(specs, key=lambda spec: spec.key)


def loader(key: str) -> LoaderSpec:
    """The loader registered under `key`. Raises `KeyError` when there is none."""
    for spec in loaders():
        if spec.key == key:
            return spec
    raise KeyError(key)
