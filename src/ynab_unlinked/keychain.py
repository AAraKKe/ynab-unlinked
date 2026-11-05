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

SERVICE_ENV = "YUL_KEYCHAIN_SERVICE"
"""Names the keychain item instead of `ynab-unlinked`: for a scratch run (`HOME=/tmp/... yul
app`) that should go through the real keychain without touching the item of the real config."""
SERVICE = os.environ.get(SERVICE_ENV) or "ynab-unlinked"
"""The keychain item: what the user sees in Keychain Access or the Credential Manager."""
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
"""Set to any value to keep the token in the config file: for scratch runs against a test
config (`HOME=/tmp/... yul app`), which would otherwise overwrite the real keychain item."""


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
        keyring.set_password(SERVICE, ACCOUNT, token)
    except Exception as error:
        raise KeychainError(str(error)) from error


def read() -> str | None:
    """The stored token, None when there is none."""
    import keyring

    try:
        return keyring.get_password(SERVICE, ACCOUNT)
    except Exception as error:
        raise KeychainError(str(error)) from error


def delete() -> None:
    """Remove the token; nothing happens when there is none."""
    import keyring
    from keyring.errors import PasswordDeleteError

    try:
        keyring.delete_password(SERVICE, ACCOUNT)
    except PasswordDeleteError:
        pass
    except Exception as error:
        raise KeychainError(str(error)) from error


def mask_token(token: str) -> str:
    """The token with its middle hidden, for screens and `yul config show`."""
    if len(token) <= 10:
        return "•" * len(token)
    return f"{token[:4]}{'•' * 16}{token[-3:]}"
