from enum import StrEnum

from ._protocol import Entity


class InputType(StrEnum):
    TXT = "txt"
    CSV = "csv"
    HTML = "html"


__all__ = ["Entity", "InputType"]
