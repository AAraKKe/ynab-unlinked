import datetime as dt
from collections.abc import Generator
from pathlib import Path
from typing import Any

import pytest
from freezegun import freeze_time
from pytest_mock import MockerFixture
from typer.testing import CliRunner as TyperRunner

from tests.helpers import assets
from tests.helpers.config import ConfigFiles
from tests.helpers.types import CliRunner
from tests.helpers.ynab_api import YnabClientStub
from ynab_unlinked.config import ConfigV2, get_config
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
def config_files(tmp_path: Path, mocker: MockerFixture) -> ConfigFiles:
    """
    Point every config path the app resolves into a scratch directory.

    Nothing exists there until a test, or the `config` fixture, writes it, so tests are free
    to save, migrate and reset configs without touching the checked in assets.
    """
    files = ConfigFiles(
        v1=tmp_path / "ynab_unlinked" / "config.json",
        v2=tmp_path / "ynab-unlinked" / "config.json",
    )

    for module in (
        "ynab_unlinked.config.core",
        "ynab_unlinked.config.models.v1",
        "ynab_unlinked.config.models.v2",
        "ynab_unlinked.privacy",
        "ynab_unlinked.commands.config",
    ):
        mocker.patch(f"{module}.config_path", side_effect=files.path)
    mocker.patch("ynab_unlinked.config.paths.v1_config_path", return_value=files.v1)
    mocker.patch("ynab_unlinked.commands.config.v1_config_path", return_value=files.v1)

    return files


@pytest.fixture
def config(request: pytest.FixtureRequest, config_files: ConfigFiles) -> str:
    """
    Install the config asset for a version and yield that version.

    The version comes from `@pytest.mark.version("V2")` or from indirect parametrization.
    Versions without an asset (such as "missing") leave the scratch directory empty.
    """
    version_marker = request.node.get_closest_marker("version")
    if version_marker and version_marker.args:
        version = version_marker.args[0]
    elif hasattr(request, "param"):
        version = request.param
    else:
        pytest.fail(
            "When using the config fixture, either:\n"
            "1. Use a version marker: @pytest.mark.version('V1')\n"
            "2. Pass a version parameter through indirect parameterization"
        )

    source = assets.path(f"config_{version}/config.json")
    if source.is_file():
        config_files.write("V1" if version == "V1" else "V2", source.read_text())

    return version


@pytest.fixture
def config_v2(config: str) -> ConfigV2:
    loaded = get_config()
    assert isinstance(loaded, ConfigV2)
    return loaded
