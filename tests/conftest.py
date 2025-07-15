import datetime as dt
from collections.abc import Generator
from contextlib import ExitStack
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from freezegun import freeze_time
from pytest_mock import MockerFixture
from typer.testing import CliRunner as TyperRunner

from tests.helpers.types import CliRunner
from tests.helpers.ynab_api import YnabClientStub
from ynab_unlinked.config import get_config
from ynab_unlinked.config.core import VERSION_MAPPING
from ynab_unlinked.context_object import YnabUnlinkedContext
from ynab_unlinked.formatter import Formatter
from ynab_unlinked.main import app
from ynab_unlinked.utils import split_quoted_string
from ynab_unlinked.ynab_api import Client


@pytest.fixture
def yul(config: str) -> CliRunner:
    def wrapper(*args: str, **kwargs: Any):
        runner = TyperRunner()
        if len(args) == 1 and " " in args[0]:
            # Handle passing all commands as a single string
            args = tuple(split_quoted_string(args[0]))
        result = runner.invoke(app, args=args, **kwargs)
        return result

    return wrapper


@pytest.fixture
def load_entity(ynab_api: YnabClientStub):
    from tests.helpers.load_entity import load_entity

    return load_entity()


@pytest.fixture
def context_obj(config: str):
    config_obj = get_config()
    assert config_obj is not None
    return YnabUnlinkedContext(
        config=config_obj,
        formatter=Formatter(
            date_format=config_obj.budget.date_format,
            currency_format=config_obj.budget.currency_format,
        ),
        extras=None,
    )


@pytest.fixture
def today() -> Generator[dt.datetime]:
    today = dt.datetime(2025, 5, 15)
    with freeze_time("2025-05-15"):
        yield today


@pytest.fixture
def ynab_api(mocker: MockerFixture):
    client_mock = mocker.patch.object(Client, "api")
    stub = YnabClientStub(api_key="someapikey")
    client_mock.side_effect = stub.api
    return stub


@pytest.fixture
def config(request: pytest.FixtureRequest) -> Generator[str]:
    """
    The config version can be requested either by marking the test with

    ```
    @pytest.mark.version("V2")
    ```

    or by passing the version as a string to the fixture request through indirect.

    If the fixture is accessed it yields the version it is pointing to
    """
    # Try to get version from marker first
    version_marker = request.node.get_closest_marker("version")
    if version_marker and version_marker.args:
        version = version_marker.args[0]
    # Fall back to fixture parameter if no marker
    elif hasattr(request, "param"):
        version = request.param
    else:
        pytest.fail(
            "When using the config fixture, either:\n"
            "1. Use a version marker: @pytest.mark.version('V1')\n"
            "2. Pass a version parameter through indirect parameterization"
        )

    config_paths_to_patch = [
        "ynab_unlinked.config.core.config_path",
        *[f"ynab_unlinked.config.models.{v.lower()}.config_path" for v in VERSION_MAPPING],
    ]

    with ExitStack() as stack:
        for module in config_paths_to_patch:

            def side_effect(v: str | None = None) -> Path:
                if not version.startswith("V"):
                    # For any special version, get whatever file is requested
                    # Make sure we do not accept any check for V1
                    if v == "V1":
                        return Path(f"tests/assets/config_{version}/no_config.json")

                    return Path(f"tests/assets/config_{version}/config.json")

                # When loading the path of a module that is not the same as the version being patched
                # set the path to a non-existing file
                if v == version:
                    return Path(f"tests/assets/config_{version}/config.json")

                return Path(f"tests/assets/config_{version}/no_config.json")

            stack.enter_context(patch(module, side_effect=side_effect))
        yield version
