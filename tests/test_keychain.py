import json

import keyring
import pytest

from tests.helpers.config import ConfigFiles
from tests.helpers.keychain import MemoryKeyring
from ynab_unlinked import keychain
from ynab_unlinked.config import LatestConfig
from ynab_unlinked.local_data import delete_local_data

pytestmark = pytest.mark.version("V4")

ITEM = (keychain.SERVICE, keychain.ACCOUNT)


def on_disk(config_files: ConfigFiles) -> str:
    return json.loads(config_files.read("V4"))["api_key"]


def test_the_token_moves_to_the_keychain_the_first_time_the_config_is_read(
    config: str, config_files: ConfigFiles, memory_keychain: MemoryKeyring
):
    assert on_disk(config_files) == "my-api-key"

    loaded = LatestConfig.load()

    assert loaded.api_key == "my-api-key"
    assert memory_keychain.passwords[ITEM] == "my-api-key"
    assert on_disk(config_files) == keychain.REFERENCE
    assert LatestConfig.load().api_key == "my-api-key"


def test_saving_writes_the_new_token_to_the_keychain_only(
    config: str, config_files: ConfigFiles, memory_keychain: MemoryKeyring
):
    loaded = LatestConfig.load()
    loaded.api_key = "a-new-token"

    loaded.save()

    assert memory_keychain.passwords[ITEM] == "a-new-token"
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
    assert ITEM in memory_keychain.passwords

    delete_local_data()

    assert memory_keychain.passwords == {}
    delete_local_data()  # nothing left to remove is not an error


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

    assert memory_keychain.passwords[ITEM] == "a-new-token"
    assert LatestConfig.load().api_key == "a-new-token"


def test_no_keychain_never_reads_the_keychain(
    memory_keychain: MemoryKeyring, monkeypatch: pytest.MonkeyPatch
):
    memory_keychain.passwords[ITEM] = "the-real-token"
    monkeypatch.setenv(keychain.NO_KEYCHAIN_ENV, "1")

    assert keychain.read() is None


@pytest.mark.parametrize(
    ("token", "masked"),
    [("short", "•••••"), ("abcd-0123456789-xyz", "abcd••••••••••••••••xyz")],
)
def test_mask_token(token: str, masked: str):
    assert keychain.mask_token(token) == masked
