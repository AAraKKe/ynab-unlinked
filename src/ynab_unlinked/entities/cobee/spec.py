from collections.abc import Mapping

from ynab_unlinked.entities import InputType
from ynab_unlinked.entities.registry import AUTO, LoaderOption, LoaderSpec, concrete

from .cobee import Cobee, CobeeContext, Language


def extras(options: Mapping[str, str]) -> CobeeContext:
    return CobeeContext(language=Language(concrete(options, "language")))


def build(options: Mapping[str, str]) -> Cobee:
    # The language only reaches the parser through the context, validate it here as well
    extras(options)
    return Cobee()


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
        ),
    ),
    build=build,
    extras=extras,
)
