# The part of pyexcel yul uses. pyexcel ships no type information.
from typing import Any

def get_array(**keywords: Any) -> list[list[Any]]:
    """Every row of the sheet named by `file_name`, cells as Python values."""
