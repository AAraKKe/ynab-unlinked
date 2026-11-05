# The part of html_text yul uses. The package is typed, but its signature names lxml's
# HtmlElement and lxml ships no types, so pyright sees that parameter as unknown.
from collections.abc import Iterable

def extract_text(
    html: str | None,
    guess_punct_space: bool = True,
    guess_layout: bool = True,
    newline_tags: Iterable[str] = ...,
    double_newline_tags: Iterable[str] = ...,
) -> str:
    """Convert html to text, cleaning invisible content such as styles."""
