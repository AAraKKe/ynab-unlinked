from enum import StrEnum
from typing import assert_never

from ._protocol import Parser, InputType
from .sabadell import SabadellParser


class ParserType(StrEnum):
    SABADELL = "Sabadell"


def get_parser(parser_type: ParserType) -> Parser:
    match parser_type:
        case ParserType.SABADELL:
            return SabadellParser()
        case _ as never:
            assert_never(never)


__all__ = ["get_parser", "InputType", "ParserType", "Parser", "SabadellParser"]
