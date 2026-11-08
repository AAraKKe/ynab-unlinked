import datetime as dt
import json
from pathlib import Path

import keyring
import pytest

from tests.helpers.config import ConfigFiles
from tests.helpers.keychain import MemoryKeyring
from ynab_unlinked import keychain
from ynab_unlinked.config import LatestConfig, update_config
from ynab_unlinked.local_data import delete_local_data

pytestmark = pytest.mark.version("V4")


def item() -> tuple[str, str]:
    return (keychain.service_name(), keychain.ACCOUNT)


def on_disk(config_files: ConfigFiles) -> str:
    return json.loads(config_files.read("V4"))["api_key"]


def test_the_token_moves_to_the_keychain_the_first_time_the_config_is_read(
    config: str, config_files: ConfigFiles, memory_keychain: MemoryKeyring
):
    assert on_disk(config_files) == "my-api-key"

    loaded = LatestConfig.load()

    assert loaded.api_key == "my-api-key"
    assert memory_keychain.passwords[item()] == "my-api-key"
    assert on_disk(config_files) == keychain.REFERENCE
    assert LatestConfig.load().api_key == "my-api-key"


def test_saving_writes_the_new_token_to_the_keychain_only(
    config: str, config_files: ConfigFiles, memory_keychain: MemoryKeyring
):
    loaded = LatestConfig.load()
    loaded.api_key = "a-new-token"

    loaded.save()

    assert memory_keychain.passwords[item()] == "a-new-token"
    assert on_disk(config_files) == keychain.REFERENCE
    assert "a-new-token" not in config_files.read("V4")


def test_without_a_keychain_the_token_stays_in_the_file(config: str, config_files: ConfigFiles):
    loaded = LatestConfig.load()
    loaded.api_key = "a-new-token"

    loaded.save()

    assert on_disk(config_files) == "a-new-token"
    assert not keychain.available()


def test_a_token_gone_from_the_keychain_loads_empty(
    config: str, config_files: ConfigFiles, memory_keychain: MemoryKeyring
):
    LatestConfig.load()
    memory_keychain.passwords.clear()

    loaded = LatestConfig.load()

    assert loaded.api_key == ""
    assert loaded.budget.name == "My Budget"


def test_deleting_the_local_data_removes_the_token_from_the_keychain(
    config: str, memory_keychain: MemoryKeyring
):
    LatestConfig.load()
    assert item() in memory_keychain.passwords

    delete_local_data()

    assert memory_keychain.passwords == {}
    delete_local_data()  # nothing left to remove is not an error


def test_a_save_that_keeps_the_token_does_not_write_it_to_the_keychain_again(
    config: str, memory_keychain: MemoryKeyring
):
    LatestConfig.load()
    assert memory_keychain.stores == 1, "The token in the file moves to the keychain once"

    update_config(lambda saved: setattr(saved, "last_reconciliation_date", dt.date(2025, 5, 10)))
    LatestConfig.load().save()
    assert memory_keychain.stores == 1

    update_config(lambda saved: setattr(saved, "api_key", "a-new-token"))
    assert memory_keychain.stores == 2
    assert memory_keychain.passwords[item()] == "a-new-token"


class RefusingKeyring(MemoryKeyring):
    """A keychain that is there but refuses to store anything (full, prompt denied)."""

    def set_password(self, service: str, username: str, password: str) -> None:
        raise RuntimeError("The keychain refused the item")


def test_a_keychain_that_refuses_the_token_leaves_it_in_the_file(
    config: str, config_files: ConfigFiles, caplog: pytest.LogCaptureFixture
):
    keyring.set_keyring(RefusingKeyring())

    loaded = LatestConfig.load()
    loaded.api_key = "a-new-token"
    loaded.save()

    assert on_disk(config_files) == "a-new-token"
    assert LatestConfig.load().api_key == "a-new-token"
    assert "the keychain failed: The keychain refused the item" in caplog.text


class LockedKeyring(MemoryKeyring):
    """A keychain that holds the token but refuses to hand it out (locked, prompt denied)."""

    def get_password(self, service: str, username: str) -> str | None:
        raise RuntimeError("User interaction is not allowed")


def test_a_save_after_a_failed_keychain_read_keeps_the_reference(
    config: str, config_files: ConfigFiles, memory_keychain: MemoryKeyring
):
    LatestConfig.load()
    locked = LockedKeyring()
    locked.passwords = memory_keychain.passwords
    keyring.set_keyring(locked)

    loaded = LatestConfig.load()
    assert loaded.api_key == ""
    loaded.set_entity_account("sabadell", "another-account")
    loaded.save()

    assert on_disk(config_files) == keychain.REFERENCE
    keyring.set_keyring(memory_keychain)
    assert LatestConfig.load().api_key == "my-api-key"


def test_a_new_token_replaces_the_unread_one(
    config: str, config_files: ConfigFiles, memory_keychain: MemoryKeyring
):
    LatestConfig.load()
    memory_keychain.passwords.clear()

    loaded = LatestConfig.load()
    loaded.api_key = "a-new-token"
    loaded.save()

    assert memory_keychain.passwords[item()] == "a-new-token"
    assert LatestConfig.load().api_key == "a-new-token"


def test_no_keychain_never_reads_the_keychain(
    memory_keychain: MemoryKeyring, monkeypatch: pytest.MonkeyPatch
):
    memory_keychain.passwords[item()] = "the-real-token"
    monkeypatch.setenv(keychain.NO_KEYCHAIN_ENV, "1")

    assert keychain.read() is None


@pytest.mark.parametrize(
    ("token", "masked"),
    [("short", "•••••"), ("abcd-0123456789-xyz", "abcd••••••••••••••••xyz")],
)
def test_mask_token(token: str, masked: str):
    assert keychain.mask_token(token) == masked


@pytest.mark.parametrize(
    ("env", "expected"),
    [
        ({}, "ynab-unlinked"),
        ({"YUL_HOME": "{home}"}, "ynab-unlinked ({home})"),
        ({"YUL_HOME": "{home}", "YUL_KEYCHAIN_SERVICE": "yul-scratch"}, "yul-scratch"),
        ({"YUL_KEYCHAIN_SERVICE": "yul-scratch"}, "yul-scratch"),
    ],
    ids=["real", "scratch-home", "named-wins", "named"],
)
def test_a_scratch_home_never_shares_the_real_keychain_item(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, env: dict[str, str], expected: str
):
    monkeypatch.delenv("YUL_HOME", raising=False)
    monkeypatch.delenv(keychain.SERVICE_ENV, raising=False)
    home = tmp_path.resolve()
    for name, value in env.items():
        monkeypatch.setenv(name, value.format(home=home))

    assert keychain.service_name() == expected.format(home=home)
