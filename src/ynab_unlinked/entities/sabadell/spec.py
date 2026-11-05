from collections.abc import Mapping

from ynab_unlinked.entities import InputType
from ynab_unlinked.entities.registry import AUTO, LoaderOption, LoaderSpec, concrete

from .sabadell import SabadellParser


def build(options: Mapping[str, str]) -> SabadellParser:
    # Sabadell writes no year, the parser moves back the rows the year would put in the future
    return SabadellParser(year=int(concrete(options, "year")))


spec = LoaderSpec(
    key="sabadell",
    name="sabadell",
    title="Sabadell",
    input_types=(InputType.TXT, InputType.XLS),
    options=(LoaderOption(key="year", label="Year of the statement", default=AUTO),),
    build=build,
    extras=None,
)
