from typing import NamedTuple, Protocol


class Version(NamedTuple):
    entity: str
    version: str

    def __ge__(self, value: tuple[str, ...]) -> bool:
        return self.version >= value[1]

    def __le__(self, value: tuple[str, ...]) -> bool:
        return self.version <= value[1]

    def __str__(self) -> str:
        return f"{self.entity}:{self.version}"

    def __repr__(self) -> str:
        return f"'{self.entity}:{self.version}'"


class Versioned(Protocol):
    @staticmethod
    def version() -> Version: ...
