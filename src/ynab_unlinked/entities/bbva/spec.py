from collections.abc import Mapping

from ynab_unlinked.entities import InputType
from ynab_unlinked.entities.registry import LoaderSpec

from .bbva import BBVA, VALID_TYPES


def build(options: Mapping[str, str]) -> BBVA:
    return BBVA()


spec = LoaderSpec(
    key="bbva",
    name="BBVA Credit Card",
    title="BBVA Credit Card",
    input_types=tuple(InputType(t) for t in VALID_TYPES),
    options=(),
    build=build,
    help="Import transactions from BBVA using a Credit Card PDF report.",
)
