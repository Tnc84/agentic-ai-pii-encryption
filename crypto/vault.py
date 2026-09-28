from __future__ import annotations

import base64
import json
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from config.settings import get_settings
from crypto.keys import NONCE_LEN, SALT_LEN, derive_key


class VaultError(RuntimeError):
    pass


def encrypt_alias_map(alias_map: dict[str, str], passphrase: str | None = None) -> tuple[str, str, str]:
    """Return (salt_b64, nonce_b64, ciphertext_b64)."""
    secret = passphrase if passphrase is not None else get_settings().vault_passphrase
    if not secret:
        raise VaultError("VAULT_PASSPHRASE is not set")

    salt = os.urandom(SALT_LEN)
    nonce = os.urandom(NONCE_LEN)
    key = derive_key(secret, salt)
    aesgcm = AESGCM(key)
    plaintext = json.dumps(alias_map, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ciphertext = aesgcm.encrypt(nonce, plaintext, None)
    return (
        base64.b64encode(salt).decode("ascii"),
        base64.b64encode(nonce).decode("ascii"),
        base64.b64encode(ciphertext).decode("ascii"),
    )


def decrypt_alias_map(
    salt_b64: str,
    nonce_b64: str,
    ciphertext_b64: str,
    passphrase: str | None = None,
) -> dict[str, str]:
    secret = passphrase if passphrase is not None else get_settings().vault_passphrase
    if not secret:
        raise VaultError("VAULT_PASSPHRASE is not set")

    salt = base64.b64decode(salt_b64)
    nonce = base64.b64decode(nonce_b64)
    ciphertext = base64.b64decode(ciphertext_b64)
    key = derive_key(secret, salt)
    aesgcm = AESGCM(key)
    try:
        plaintext = aesgcm.decrypt(nonce, ciphertext, None)
    except Exception as exc:  # noqa: BLE001
        raise VaultError("Failed to decrypt vault map") from exc
    data = json.loads(plaintext.decode("utf-8"))
    if not isinstance(data, dict):
        raise VaultError("Invalid vault payload")
    return {str(k): str(v) for k, v in data.items()}
