from dataclasses import dataclass
from pathlib import Path

from tests.helpers import assets


@dataclass
class ConfigFiles:
    """Where each config version lives for the duration of a test."""

    v1: Path
    v2: Path

    def path(self, version: str = "V2") -> Path:
        return self.v1 if version == "V1" else self.v2

    def write(self, version: str, content: str) -> Path:
        target = self.path(version)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
        return target

    def write_asset(self, version: str) -> Path:
        return self.write(version, assets.read_text(f"config_{version}/config.json"))

    def read(self, version: str = "V2") -> str:
        return self.path(version).read_text()
