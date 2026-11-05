"""What every entity package offers as a loader, discovered at runtime.

Each entity package exposes a module level `spec: LoaderSpec`. Frontends list them with
`loaders()`, show their options, and build the entity with concrete option values.
"""

from __future__ import annotations

import importlib
import pkgutil
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

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
    """Options to entity instance. Raises `ValueError` on a missing, `auto` or invalid value."""
    extras: Callable[[Mapping[str, str]], Any] | None
    """Options to `context.extras`, for the entities that read it."""

    def accepts(self, input_file: Path) -> bool:
        # Same rule as `utils.extract_type`: the suffix as written, without the dot
        return input_file.suffix[1:] in self.input_types

    def context_extras(self, options: Mapping[str, str]) -> Any:
        return None if self.extras is None else self.extras(options)


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
