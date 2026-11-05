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
from tests.helpers.keychain import MemoryKeyring
from tests.helpers.types import CliRunner
from tests.helpers.ynab_api import YnabClientStub
from ynab_unlinked import keychain
from ynab_unlinked.cli.context_object import YnabUnlinkedContext
from ynab_unlinked.cli.utils import split_quoted_string
from ynab_unlinked.config import ConfigV3, ConfigV4, get_config
from ynab_unlinked.config.paths import HOME_ENV, web_storage_dir
from ynab_unlinked.formatter import Formatter
from ynab_unlinked.main import app
from ynab_unlinked.store import store_path
from ynab_unlinked.ynab_api import Client

# Sets a scratch storage path for NiceGUI and provides its simulated `User` (tests/web)
pytest_plugins = ["nicegui.testing.user_plugin"]


@pytest.fixture(autouse=True)
def yul_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Every file yul reads or writes lives under a scratch `YUL_HOME` for every test.

    The code honours `YUL_HOME` everywhere, so a test that skips the other fixtures, or a
    module that imports a path function the fixtures do not patch, still never reaches the
    real config, budget copy, preferences or keychain item.
    """
    home = tmp_path / "data"
    monkeypatch.setenv(HOME_ENV, str(home))
    monkeypatch.delenv(keychain.SERVICE_ENV, raising=False)
    return home


@pytest.fixture(autouse=True)
def no_keychain() -> Generator[None]:
    """Tests never touch the real keychain: the token stays in the config file as plain text
    unless the test asks for `memory_keychain`."""
    import keyring
    from keyring.backends import fail

    previous = keyring.get_keyring()
    keyring.set_keyring(fail.Keyring())
    yield
    keyring.set_keyring(previous)


@pytest.fixture
def memory_keychain() -> MemoryKeyring:
    """A keychain that forgets everything when the test ends."""
    import keyring

    backend = MemoryKeyring()
    keyring.set_keyring(backend)
    return backend


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

    Apart from `YUL_HOME` (which holds the budget copy and the preferences), so a reset
    lists the config folder and the store as two paths, as on a real install. Nothing
    exists there until a test, or the `config` fixture, writes it, so tests are free to
    save, migrate and reset configs without touching the checked in assets.
    """
    files = ConfigFiles(
        v1=tmp_path / "ynab_unlinked" / "config.json",
        v2=tmp_path / "ynab-unlinked" / "config.json",
    )

    for module in (
        "ynab_unlinked.config.core",
        "ynab_unlinked.config.models.v1",
        "ynab_unlinked.config.models.v2",
        "ynab_unlinked.config.models.v3",
        "ynab_unlinked.config.models.v4",
        "ynab_unlinked.privacy",
        "ynab_unlinked.local_data",
    ):
        mocker.patch(f"{module}.config_path", side_effect=files.path)
    mocker.patch("ynab_unlinked.config.paths.v1_config_path", return_value=files.v1)
    mocker.patch("ynab_unlinked.local_data.v1_config_path", return_value=files.v1)

    return files


@pytest.fixture
def store_file(yul_home: Path) -> Path:
    """Where the local store lives in this test: `store.sqlite` under the scratch `YUL_HOME`.

    Nothing exists there until a test opens a `Store` on it.
    """
    return store_path()


@pytest.fixture
def web_storage(yul_home: Path) -> Path:
    """Where the web app preferences live in this test, under the scratch `YUL_HOME`."""
    return web_storage_dir()


@pytest.fixture
def config(request: pytest.FixtureRequest, config_files: ConfigFiles) -> str:
    """
    Install the config asset for a version and yield that version.

    The version comes from `@pytest.mark.version("V4")` or from indirect parametrization.
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
def config_v3(config: str) -> ConfigV3:
    """The stored config read as V3, without migrating it to the latest version."""
    return ConfigV3.load()


@pytest.fixture
def config_v4(config: str) -> ConfigV4:
    loaded = get_config()
    assert isinstance(loaded, ConfigV4)
    return loaded
