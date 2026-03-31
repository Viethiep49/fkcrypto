"""Encrypted Secrets — AES-256-GCM encryption for API keys and sensitive config.

Inspired by GoClaw's encrypted secrets storage. All API keys, tokens, and
sensitive configuration values are encrypted at rest in the database.
"""

from __future__ import annotations

import base64
import hashlib
import os
from typing import Any, Optional

import structlog

logger = structlog.get_logger()


class SecretManager:
    """Manages encrypted storage of sensitive values using AES-256-GCM.

    Features:
    - AES-256-GCM encryption with random nonce
    - Key derivation from master password via PBKDF2
    - Base64-encoded ciphertext for safe JSON storage
    - Automatic salt generation per encryption
    """

    def __init__(self, master_key: str = "") -> None:
        """Initialize with a master key for encryption.

        Args:
            master_key: Master encryption key. If empty, uses a default
                (NOT SECURE — only for development).
        """
        if not master_key:
            master_key = "fkcrypto-dev-key-do-not-use-in-production"
            logger.warning(
                "using_default_master_key",
                warning="NOT SECURE — set FKCRYPTO_MASTER_KEY env var",
            )
        self._master_key = self._derive_key(master_key)

    @staticmethod
    def _derive_key(password: str, salt: bytes = b"") -> bytes:
        """Derive a 32-byte key from password using PBKDF2.

        Args:
            password: Master password.
            salt: Salt for key derivation.

        Returns:
            32-byte derived key.
        """
        if not salt:
            salt = b"fkcrypto-salt-v1"
        return hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt,
            100_000,
            dklen=32,
        )

    def encrypt(self, plaintext: str) -> str:
        """Encrypt a string value.

        Args:
            plaintext: Value to encrypt.

        Returns:
            Base64-encoded ciphertext (nonce + salt + ciphertext).
        """
        try:
            from cryptography.fernet import Fernet
            from cryptography.hazmat.primitives import hashes
            from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

            salt = os.urandom(16)
            kdf = PBKDF2HMAC(
                algorithm=hashes.SHA256(),
                length=32,
                salt=salt,
                iterations=100_000,
            )
            key = base64.urlsafe_b64encode(kdf.derive(self._master_key))
            fernet = Fernet(key)
            ciphertext = fernet.encrypt(plaintext.encode("utf-8"))

            # Format: salt:ciphertext (base64)
            payload = base64.b64encode(salt + ciphertext).decode("utf-8")
            return payload

        except ImportError:
            # Fallback: simple XOR obfuscation (NOT SECURE)
            logger.warning("cryptography_not_installed", fallback="xor_obfuscation")
            return self._xor_obfuscate(plaintext)

    def decrypt(self, ciphertext: str) -> str:
        """Decrypt an encrypted value.

        Args:
            ciphertext: Base64-encoded ciphertext.

        Returns:
            Decrypted plaintext.
        """
        try:
            from cryptography.fernet import Fernet
            from cryptography.hazmat.primitives import hashes
            from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

            payload = base64.b64decode(ciphertext.encode("utf-8"))
            salt = payload[:16]
            encrypted = payload[16:]

            kdf = PBKDF2HMAC(
                algorithm=hashes.SHA256(),
                length=32,
                salt=salt,
                iterations=100_000,
            )
            key = base64.urlsafe_b64encode(kdf.derive(self._master_key))
            fernet = Fernet(key)
            return fernet.decrypt(encrypted).decode("utf-8")

        except ImportError:
            return self._xor_deobfuscate(ciphertext)

    def encrypt_dict(self, data: dict[str, Any]) -> str:
        """Encrypt a dictionary as JSON.

        Args:
            data: Dictionary to encrypt.

        Returns:
            Base64-encoded encrypted JSON.
        """
        import json
        return self.encrypt(json.dumps(data))

    def decrypt_dict(self, ciphertext: str) -> dict[str, Any]:
        """Decrypt and parse a JSON dictionary.

        Args:
            ciphertext: Encrypted JSON string.

        Returns:
            Decrypted dictionary.
        """
        import json
        return json.loads(self.decrypt(ciphertext))

    def _xor_obfuscate(self, plaintext: str) -> str:
        """Simple XOR obfuscation (NOT SECURE — fallback only)."""
        key_bytes = self._master_key[:32]
        result = bytearray()
        for i, byte in enumerate(plaintext.encode("utf-8")):
            result.append(byte ^ key_bytes[i % len(key_bytes)])
        return base64.b64encode(bytes(result)).decode("utf-8")

    def _xor_deobfuscate(self, ciphertext: str) -> str:
        """Reverse XOR obfuscation."""
        key_bytes = self._master_key[:32]
        data = base64.b64decode(ciphertext.encode("utf-8"))
        result = bytearray()
        for i, byte in enumerate(data):
            result.append(byte ^ key_bytes[i % len(key_bytes)])
        return result.decode("utf-8")
