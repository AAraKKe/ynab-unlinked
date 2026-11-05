import pytest

from ynab_unlinked.core.detect import resolve_options
from ynab_unlinked.entities.registry import LoaderSpec, loader, loaders


@pytest.mark.parametrize("spec", loaders(), ids=lambda spec: spec.key)
def test_a_loader_is_named_like_its_entity(spec: LoaderSpec):
    """The account of an entity is saved in the config under `Entity.name()`. A spec with
    another name would look up, and show, the wrong account."""
    assert spec.build(resolve_options(spec)).name() == spec.name


def test_every_shipped_bank_is_a_loader():
    assert [spec.key for spec in loaders()] == ["bbva", "cobee", "sabadell"]


def test_an_unknown_loader_is_a_key_error():
    with pytest.raises(KeyError):
        loader("unknown-bank")


@pytest.mark.parametrize(
    ("key", "options"),
    [
        pytest.param("sabadell", {"year": "auto"}, id="sabadell-year-left-to-auto"),
        pytest.param("sabadell", {}, id="sabadell-year-missing"),
        pytest.param("sabadell", {"year": "last"}, id="sabadell-year-not-a-number"),
        pytest.param("cobee", {"language": "auto"}, id="cobee-language-left-to-auto"),
        pytest.param("cobee", {"language": "fr"}, id="cobee-language-not-supported"),
    ],
)
def test_building_a_loader_needs_concrete_options(key: str, options: dict[str, str]):
    with pytest.raises(ValueError):
        loader(key).build(options)
