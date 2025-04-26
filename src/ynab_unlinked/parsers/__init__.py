from enum import StrEnum

from ._protocol import Parser, InputType
from .sabadell import SabadellParser


class ParserType(StrEnum):
    SABADELL = "Sabadell"

__all__ = ["InputType", "ParserType", "Parser", "SabadellParser"]