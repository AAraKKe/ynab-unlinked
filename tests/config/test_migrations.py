from collections.abc import Generator
from dataclasses import dataclass

import pytest

from ynab_unlinked.config.migrations import Delta, DeltaRegistry, MigrationEngine, Version


@dataclass
class UserV1:
    name: str
    age: int

    @staticmethod
    def version() -> Version:
        return Version("User", "V1")


@dataclass
class UserV2:
    name: str
    age: int
    email: str

    @staticmethod
    def version() -> Version:
        return Version("User", "V2")


@dataclass
class UserV3:
    name: str
    age: int
    email: str
    address: str | None

    @staticmethod
    def version() -> Version:
        return Version("User", "V3")


@dataclass
class Other:
    prop: int

    @staticmethod
    def version() -> Version:
        return Version("Other", "V1")


class DeltaUserV1V2(Delta[UserV1, UserV2]):
    origin = UserV1.version()
    destination = UserV2.version()

    def on_migrate(self, origin: UserV1) -> UserV2:
        return UserV2(name=origin.name, age=origin.age, email="default@email.com")

    def on_rollback(self, destination: UserV2) -> UserV1:
        return UserV1(
            name=destination.name,
            age=destination.age,
        )


class DeltaUserV2V3(Delta[UserV2, UserV3]):
    origin = UserV2.version()
    destination = UserV3.version()

    def on_migrate(self, origin: UserV2) -> UserV3:
        return UserV3(
            name=origin.name,
            age=origin.age,
            email=origin.email,
            address=None,
        )

    def on_rollback(self, destination: UserV3) -> UserV2:
        return UserV2(
            name=destination.name,
            age=destination.age,
            email=destination.email,
        )


@pytest.fixture
def v1() -> UserV1:
    return UserV1(name="John", age=24)


@pytest.fixture
def v2() -> UserV2:
    return UserV2(name="John", age=24, email="john@domain.com")


@pytest.fixture
def v3() -> UserV3:
    return UserV3(name="John", age=24, email="john@domain.com", address="My Street, My City")


@pytest.fixture
def registry() -> DeltaRegistry:
    registry = DeltaRegistry("User")

    registry.add_delta(DeltaUserV1V2())
    registry.add_delta(DeltaUserV2V3())

    return registry


@pytest.fixture
def engine() -> Generator[MigrationEngine]:
    yield MigrationEngine("User", DeltaUserV1V2(), DeltaUserV2V3())

    MigrationEngine._deltas = {}


def test_version():
    assert Version("User", "V2") > Version("User", "V1")
    assert Version("User", "V2") >= Version("User", "V1")
    assert Version("User", "V2") >= Version("User", "V2")
    assert Version("User", "V2") == Version("User", "V2")
    assert Version("User", "V2") <= Version("User", "V2")
    assert Version("User", "V1") <= Version("User", "V2")
    assert Version("User", "V1") < Version("User", "V2")


def test_delta_migrate(v1: UserV1):
    delta = DeltaUserV1V2()

    v2 = delta.migrate(v1)

    assert v2.name == v1.name
    assert v2.age == v1.age
    assert v2.email == "default@email.com"


def test_delta_rollback(v2: UserV2):
    delta = DeltaUserV1V2()

    v1 = delta.rollback(v2)

    assert v2.name == v1.name
    assert v2.age == v1.age
    assert not hasattr(v1, "email")


def test_delta_cannot_migrate_unknown_version():
    delta = DeltaUserV1V2()

    with pytest.raises(ValueError, match="not supported by this Delta"):
        delta.migrate(Other(prop=1))  # type: ignore


def test_delta_cannot_rollback_unknown_version():
    delta = DeltaUserV1V2()

    with pytest.raises(ValueError, match="not supported by this Delta"):
        delta.rollback(Other(prop=1))  # type: ignore


def test_registry_cannot_register_multiple_delta_per_version():
    registry = DeltaRegistry("User")
    registry.add_delta(DeltaUserV1V2())

    with pytest.raises(ValueError, match="has already been registered for version V1"):
        registry.add_delta(DeltaUserV1V2())


def test_delta_sequence_includes_needed_delta(registry: DeltaRegistry):
    sequence = registry.migration_sequence(UserV1.version(), UserV2.version())

    assert len(sequence) == 1
    assert isinstance(sequence[0], DeltaUserV1V2)


def test_delta_sequence_includes_needed_deltas(registry: DeltaRegistry):
    sequence = registry.migration_sequence(UserV1.version(), UserV3.version())

    assert len(sequence) == 2
    assert isinstance(sequence[0], DeltaUserV1V2)
    assert isinstance(sequence[1], DeltaUserV2V3)


def test_delta_sequence_for_rollbacks(registry: DeltaRegistry):
    sequence = registry.migration_sequence(UserV3.version(), UserV1.version())

    assert len(sequence) == 2
    assert isinstance(sequence[0], DeltaUserV2V3)
    assert isinstance(sequence[1], DeltaUserV1V2)


def test_delta_sequence_error_with_wrong_entity(registry: DeltaRegistry):
    with pytest.raises(ValueError, match="Cannot find a sequence between different entities"):
        registry.migration_sequence(UserV1.version(), Other.version())


def test_delta_sequence_error_without_registered_delta():
    registry = DeltaRegistry("User")
    registry.add_delta(DeltaUserV1V2())

    with pytest.raises(ValueError, match="Cannot find a migration sequence matching V1 -> V3"):
        registry.migration_sequence(UserV1.version(), UserV3.version())


def test_delta_sequence_empty_for_no_change(registry: DeltaRegistry):
    sequence = registry.migration_sequence(UserV1.version(), UserV1.version())

    assert len(sequence) == 0


def test_cannot_register_twice_same_class():
    MigrationEngine("Something")

    with pytest.raises(ValueError, match="has already been registered"):
        MigrationEngine("Something")

    MigrationEngine._deltas = {}


def test_migration_through_engine(v1: UserV1, engine: MigrationEngine):
    v2 = engine.migrate(v1, UserV2)

    assert v2.name == v1.name
    assert v2.age == v1.age
    assert v2.email == "default@email.com"


def test_migration_through_engine_full_sequence(v1: UserV1, engine: MigrationEngine):
    v2 = engine.migrate(v1, UserV3)

    assert v2.name == v1.name
    assert v2.age == v1.age
    assert v2.email == "default@email.com"
    assert v2.address is None


def test_rollbacks_through_engine(v2: UserV2, engine: MigrationEngine):
    v1 = engine.rollback(v2, UserV1)

    assert v2.name == v1.name
    assert v2.age == v1.age
    assert not hasattr(v1, "email")


def test_rollback_through_engine_full_sequence(v3: UserV3, engine: MigrationEngine):
    v1 = engine.rollback(v3, UserV1)

    assert v1.name == v3.name
    assert v1.age == v3.age
    assert not hasattr(v1, "email")
    assert not hasattr(v1, "address")


def test_migration_fails_with_different_entities(v3: UserV3, engine: MigrationEngine):
    with pytest.raises(ValueError, match="Cannot handle migrations on diferent entities"):
        engine.migrate(v3, Other)


def test_rollback_fails_with_different_entities(v3: UserV3, engine: MigrationEngine):
    with pytest.raises(ValueError, match="Cannot handle migrations on diferent entities"):
        engine.rollback(v3, Other)


def test_migration_fails_for_unregistered_entity(engine: MigrationEngine):
    with pytest.raises(ValueError, match="No migrations have been registered for 'Other'"):
        engine.migrate(Other(prop=1), Other)


def test_rollback_fails_for_unregistered_entity(engine: MigrationEngine):
    with pytest.raises(ValueError, match="No migrations have been registered for 'Other'"):
        engine.rollback(Other(prop=1), Other)
