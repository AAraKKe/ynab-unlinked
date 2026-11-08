"""The YNAB token in the operating system's keychain, through `keyring`.

macOS Keychain, Windows Credential Manager, Secret Service (GNOME Keyring) or KWallet on
Linux. When no keychain is available (a headless Linux box, say) the token stays in the
config file as before. With a keychain, the config file holds `REFERENCE` instead of the
token, and `ConfigV4.load()` reads the token back from here.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from ynab_unlinked.config.paths import yul_home

SERVICE_ENV = "YUL_KEYCHAIN_SERVICE"
"""Names the keychain item instead of the default one."""
DEFAULT_SERVICE = "ynab-unlinked"


def service_name() -> str:
    """The keychain item for this run: what the user sees in Keychain Access.

    `YUL_KEYCHAIN_SERVICE` when set. Otherwise a run with `YUL_HOME` (a scratch run) gets
    an item of its own, `ynab-unlinked (<YUL_HOME>)`, so it can never overwrite the token of
    the real config; without either it is `ynab-unlinked`. Read at every use, so a change
    of the environment after import (a test, a scratch run) picks its own item.
    """
    if name := os.environ.get(SERVICE_ENV):
        return name
    if (home := yul_home()) is not None:
        return f"{DEFAULT_SERVICE} ({home.resolve()})"
    return DEFAULT_SERVICE


ACCOUNT = "YNAB Personal Access Token"
REFERENCE = "@keychain"
"""What the config file holds in `api_key` when the token lives in the keychain."""

logger = logging.getLogger(__name__)

_NAMES = {
    "macOS": "macOS Keychain",
    "Windows": "Windows Credential Manager",
    "SecretService": "Secret Service (GNOME Keyring)",
    "kwallet": "KWallet",
}


class KeychainError(Exception):
    """The keychain refused to store, read or delete the token."""


def _backend() -> Any:
    import keyring

    backend = keyring.get_keyring()
    backends = getattr(backend, "backends", None)
    if backends is not None:
        # A chainer: the first viable backend answers
        return backends[0] if backends else None
    return backend


NO_KEYCHAIN_ENV = "YUL_NO_KEYCHAIN"
"""Set to any value to keep the token in the config file, out of any keychain."""


def available() -> bool:
    """Whether this computer has a keychain yul can use (and `YUL_NO_KEYCHAIN` is not set)."""
    if os.environ.get(NO_KEYCHAIN_ENV):
        return False
    try:
        backend = _backend()
    except Exception:
        return False
    return backend is not None and getattr(backend, "priority", 0) >= 1


def backend_name() -> str | None:
    """ "macOS Keychain", "Windows Credential Manager"... None without a keychain."""
    if not available():
        return None
    backend = _backend()
    module = type(backend).__module__
    return next((name for key, name in _NAMES.items() if key in module), type(backend).__name__)


def store(token: str) -> None:
    import keyring

    try:
        keyring.set_password(service_name(), ACCOUNT, token)
    except Exception as error:
        raise KeychainError(str(error)) from error


def read() -> str | None:
    """The stored token, None when there is none or `YUL_NO_KEYCHAIN` is set."""
    if os.environ.get(NO_KEYCHAIN_ENV):
        return None
    import keyring

    try:
        return keyring.get_password(service_name(), ACCOUNT)
    except Exception as error:
        raise KeychainError(str(error)) from error


def delete() -> None:
    """Remove the token; nothing happens when there is none."""
    import keyring
    from keyring.errors import PasswordDeleteError

    try:
        keyring.delete_password(service_name(), ACCOUNT)
    except PasswordDeleteError:
        pass
    except Exception as error:
        raise KeychainError(str(error)) from error


def mask_token(token: str) -> str:
    """The token with its middle hidden, for screens and `yul config show`."""
    if len(token) <= 10:
        return "•" * len(token)
    return f"{token[:4]}{'•' * 16}{token[-3:]}"
