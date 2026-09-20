from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from pytest_mock import MockerFixture

from tests.factories import CurrencyFormatFactory
from ynab_unlinked.formatter import Formatter


@pytest.fixture
def formatter() -> Formatter:
    return Formatter("DD/MM/YYYY", CurrencyFormatFactory.build())


@pytest.fixture
def printed(mocker: MockerFixture) -> MagicMock:
    """Captures the renderables handed to the console instead of rendering them."""
    return mocker.patch("ynab_unlinked.utils.console").return_value.print
