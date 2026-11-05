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
    options=(
        LoaderOption(
            key="year",
            label="Year of the statement",
            default=AUTO,
            flags=("-y", "--year"),
            help=(
                "Year of the transactions to import. Sabadell statements do not include the year in the date, "
                "so you need to specify it. If not specified, the current year will be used."
            ),
            integer=True,
        ),
    ),
    build=build,
    help="""
    Inputs transactions from a Sabadell TXT or XLS file.

    From your Sabadell Credit Card statement, you can download a txt file with the transactions.
    At the moment only txt format is supported.
    """,
)
