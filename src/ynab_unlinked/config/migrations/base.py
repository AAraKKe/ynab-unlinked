from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from contextlib import nullcontext
from functools import reduce
from typing import cast

from ynab_unlinked import display

from .types import Version, Versioned


class Delta[V1: Versioned, V2: Versioned](ABC):
    origin: Version
    destination: Version

    def __init_subclass__(cls) -> None:
        class_name = cls.__name__
        if not hasattr(cls, "origin"):
            raise ValueError(f"Class {class_name} needs to define an 'origin' class variable.")

        if not hasattr(cls, "destination"):
            raise ValueError(f"Class {class_name} needs to define an 'destination' class variable.")

    @abstractmethod
    def on_migrate(self, origin: V1) -> V2: ...

    def migrate(self, origin: V1) -> V2:
        """Method to migrate from the delta origin to the destination"""
        if origin.version() != self.origin:
            error_msg = (
                "The origin version supplied to migrate is not supported by this Delta: "
                f"{origin.version()} != {self.origin}"
            )
            raise ValueError(error_msg)

        return self.on_migrate(origin)

    @abstractmethod
    def on_rollback(self, destination: V2) -> V1: ...

    def rollback(self, destination: V2) -> V1:
        """Method to rollback from the Delta destination to its origin"""
        if destination.version() != self.destination:
            error_msg = (
                "The origin supplied to migrate is not supported by this Delta: "
                f"{destination.version()} != {self.destination}"
            )
            raise ValueError(error_msg)

        return self.on_rollback(destination)


class DeltaRegistry:
    def __init__(self, cls: str):
        self.cls = cls
        self.origins: dict[str, Delta] = {}
        self.destinations: dict[str, Delta] = {}

    def add_delta(self, delta: Delta):
        """Registers delta in the registry"""
        if delta.origin.version in self.origins:
            raise ValueError(
                f"A delta has already been registered for version {delta.origin.version}"
            )
        self.origins[delta.origin.version] = delta
        self.destinations[delta.destination.version] = delta

    def migration_sequence(self, origin: Version, destination: Version) -> Sequence[Delta]:
        """
        Returns a sequence of detlas to be chained to reach the version in `destination`
        from the `origin` version.
        """
        if origin.entity != destination.entity:
            raise ValueError(
                "Cannot find a sequence between different entities: "
                f"[{origin.entity!r}, {destination.entity!r}]"
            )

        if origin == destination:
            return []

        sequence = []
        is_rollback = origin > destination
        current_delta = (
            self.destinations.get(origin.version)
            if is_rollback
            else self.origins.get(origin.version)
        )

        while current_delta:
            sequence.append(current_delta)
            if (
                # During rollback we are moving backwards
                is_rollback
                and current_delta.origin.version == destination.version
                or current_delta.destination.version == destination.version
            ):
                break

            current_delta = (
                self.destinations.get(current_delta.origin.version)
                if is_rollback
                else self.origins.get(current_delta.destination.version)
            )
        else:
            # Reach this when while ends naturally, i.e. no delta found for the next migration
            raise ValueError(
                f"Cannot find a migration sequence matching {origin.version} -> {destination.version}."
            )

        return sequence


class MigrationEngine:
    _deltas: dict[str, DeltaRegistry] = {}

    def __init__(self, cls: str, *deltas: Delta):
        if cls in self.__class__._deltas:
            raise ValueError(f"The class {cls!r} has already been registered for migrations")

        registry = DeltaRegistry(cls)
        for delta in deltas:
            registry.add_delta(delta)

        self.__class__._deltas[cls] = registry

    def __prepare_sequence(self, origin: Version, destination: Version) -> Sequence[Delta]:
        origin_entity, _ = origin
        destination_entity, _ = destination

        if origin_entity != destination_entity:
            raise ValueError(
                f"Cannot handle migrations on diferent entities: ({origin_entity!r} -> {destination_entity!r})"
            )

        if registry := self._deltas.get(origin_entity):
            return registry.migration_sequence(origin=origin, destination=destination)

        raise ValueError(f"No migrations have been registered for {origin_entity!r}")

    def migrate[V: Versioned](self, origin: Versioned, to_type: type[V]) -> V:
        deltas: Sequence[Delta[Versioned, V]] = self.__prepare_sequence(
            origin.version(), to_type.version()
        )

        process_context = display.process if deltas else lambda *args, **kwargs: nullcontext()

        with process_context(
            f"Migrating {origin.version()} to {to_type.version()}", "Migration done!"
        ):
            # Use of cast because migrate does not produce the same type as output as its input and reduce expects that
            result = cast(V, reduce(lambda result, delta: delta.migrate(result), deltas, origin))

        if not isinstance(result, to_type):
            raise TypeError(
                "Unexpected type mismatch. The result of the migration "
                f"returned {type(result)!r} but {to_type!r} was expected"
            )

        return result

    def rollback[V: Versioned](self, destination: Versioned, to_type: type[V]) -> V:
        deltas: Sequence[Delta[Versioned, V]] = self.__prepare_sequence(
            destination.version(), to_type.version()
        )

        # Ignore typing for a similar reason as in migrate but with the complication that
        # now the types to be returned are inverted
        result: V = reduce(
            lambda result, delta: delta.rollback(result),  # type: ignore
            deltas,
            destination,
        )

        return result
