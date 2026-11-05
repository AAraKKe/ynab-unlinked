from __future__ import annotations

import datetime as dt
import logging
import os
import tempfile
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr

from ynab_unlinked import keychain
from ynab_unlinked.buckets import Bucket
from ynab_unlinked.config.migrations import Version
from ynab_unlinked.config.paths import config_path

from .v2 import Budget

logger = logging.getLogger(__name__)


class LoaderConfig(BaseModel):
    account_id: str
    options: dict[str, str] = Field(default_factory=dict)
    enabled: bool = True
    """Off keeps the account and options but `load auto` and the app skip the bank."""


class TrackedAccount(BaseModel):
    id: str
    name: str
    # YNAB AccountType value, refreshed from the API
    type: str
    bucket: Bucket
    track_balance: bool = False
    """Its balance is entered by hand in the net worth view."""
    counted: bool = True
    """Off leaves the account out of net worth. Every open account counts by default."""


class DebtMapping(BaseModel):
    debt_account_id: str
    mapped_to: list[str] = Field(default_factory=list)


class ClearedStatus(StrEnum):
    CLEARED = "cleared"
    UNCLEARED = "uncleared"
    RECONCILED = "reconciled"


class Adjustments(BaseModel):
    memo: str = "Balance adjustment by yul"
    payee: str = "Balance Adjustment"
    cleared: ClearedStatus = ClearedStatus.CLEARED


def _write_private(path: Path, text: str) -> None:
    """Write through a user only temp file in the same directory, then swap it in."""
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    # mkstemp creates the file with mode 0o600
    fd, temp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            file.write(text)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temp, path)
    except BaseException:
        Path(temp).unlink(missing_ok=True)
        raise


class ConfigV4(BaseModel):
    api_key: str
    budget: Budget
    last_reconciliation_date: dt.date | None = None
    # Keyed by Entity.name()
    loaders: dict[str, LoaderConfig] = Field(default_factory=dict)
    accounts: list[TrackedAccount] = Field(default_factory=list)
    adjustments: Adjustments = Field(default_factory=Adjustments)
    debt_mappings: list[DebtMapping] = Field(default_factory=list)
    version_number: str = Field(default="V4", alias="version")

    model_config = ConfigDict(validate_by_alias=True, serialize_by_alias=True)

    _keychain_unread: bool = PrivateAttr(default=False)
    """The file points to the keychain but the token could not be read from it. A save with
    no new token writes the reference back, so the file still finds the token later."""

    @staticmethod
    def version() -> Version:
        return Version("Config", "V4")

    @staticmethod
    def path() -> Path:
        return config_path(ConfigV4.version().version)

    def save(self):
        """Write the file; the token goes to the keychain when there is one.

        The file then holds `keychain.REFERENCE` in its place. Without a keychain, or when it
        refuses the token, the token is written in plain text as before. The file is readable
        by the user only and replaced in one step, so a crash never leaves half of it.
        """
        on_disk = self
        if self.api_key and self.api_key != keychain.REFERENCE and keychain.available():
            try:
                keychain.store(self.api_key)
            except keychain.KeychainError as error:
                logger.warning("The token stays in the config file, the keychain failed: %s", error)
            else:
                on_disk = self.model_copy(update={"api_key": keychain.REFERENCE})
        elif not self.api_key and self._keychain_unread:
            on_disk = self.model_copy(update={"api_key": keychain.REFERENCE})
        _write_private(self.path(), on_disk.model_dump_json(indent=4))

    @staticmethod
    def load() -> ConfigV4:
        """Read the file and the token from the keychain.

        `api_key` is empty when the keychain no longer has the token (or refuses to give it):
        the caller asks for it again. A token still in the file moves to the keychain once.
        """
        config = ConfigV4.model_validate_json(ConfigV4.path().read_text())
        if config.api_key == keychain.REFERENCE:
            try:
                config.api_key = keychain.read() or ""
            except keychain.KeychainError as error:
                logger.warning("The token could not be read from the keychain: %s", error)
                config.api_key = ""
            config._keychain_unread = not config.api_key
        elif config.api_key and keychain.available():
            config.save()
        return config

    @staticmethod
    def exists() -> bool:
        return ConfigV4.path().is_file()

    def entity(self, name: str) -> LoaderConfig | None:
        return self.loaders.get(name)

    def set_entity_account(self, name: str, account_id: str):
        if (loader := self.loaders.get(name)) is None:
            self.loaders[name] = LoaderConfig(account_id=account_id)
        else:
            loader.account_id = account_id

    def account(self, id: str) -> TrackedAccount | None:
        return next((account for account in self.accounts if account.id == id), None)

    def debt_mapping(self, debt_account_id: str) -> DebtMapping | None:
        return next(
            (
                mapping
                for mapping in self.debt_mappings
                if mapping.debt_account_id == debt_account_id
            ),
            None,
        )
