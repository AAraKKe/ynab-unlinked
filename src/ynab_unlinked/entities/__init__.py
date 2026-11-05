from enum import StrEnum

from ._protocol import Entity, Match


class InputType(StrEnum):
    TXT = "txt"
    CSV = "csv"
    HTML = "html"
    XLS = "xls"
    XLSX = "xlsx"
    PDF = "pdf"


__all__ = ["Entity", "InputType", "Match"]
