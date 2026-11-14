import pytest

from ynab_unlinked.config.models.v2 import CurrencyFormat
from ynab_unlinked.web import theme
from ynab_unlinked.web.components.cashflow_chart import histogram_options

PALETTE = theme.DARK_PALETTE
FORMAT = CurrencyFormat(
    iso_code="EUR",
    decimal_digits=2,
    decimal_separator=".",
    symbol_first=False,
    group_separator=",",
    currency_symbol="€",
    display_symbol=True,
)


@pytest.mark.parametrize(
    ("bins", "decimals"),
    [
        pytest.param([(10_000, 12_000, 3), (12_000, 14_000, 1)], 0, id="whole units"),
        pytest.param([(15_000, 15_500, 3), (15_500, 16_000, 1)], 2, id="narrower than a unit"),
    ],
)
def test_slices_narrower_than_a_unit_are_written_with_decimals(
    bins: list[tuple[int, int, int]], decimals: int
):
    label = histogram_options(bins, PALETTE, FORMAT)["xAxis"]["axisLabel"][":formatter"]

    assert f"toFixed({decimals})" in label
