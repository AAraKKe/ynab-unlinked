from collections.abc import Mapping

from ynab_unlinked.entities import InputType
from ynab_unlinked.entities.registry import AUTO, LoaderOption, LoaderSpec, concrete

from .cobee import Cobee, Language


def build(options: Mapping[str, str]) -> Cobee:
    return Cobee(language=Language(concrete(options, "language")))


spec = LoaderSpec(
    key="cobee",
    name="cobee",
    title="Cobee",
    input_types=(InputType.HTML,),
    options=(
        LoaderOption(
            key="language",
            label="Language of the saved page",
            default=AUTO,
            choices=(AUTO, *(language.value for language in Language)),
            flags=("-l", "--lang", "--language"),
            help="Language used when exporting the HTML webisite",
        ),
    ),
    build=build,
    help="""
    Import transactions from a Cobee HTML file.

    Cobee that not support exporting transactions. To use the Cobee entity, form the website,
    find the list of transactions of the month you want to import into YNAB and save the page as HTML.

    You cando this by Right Click > Save as, and select where you want to save the file.
    """,
)
