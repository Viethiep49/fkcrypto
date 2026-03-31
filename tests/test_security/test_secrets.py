"""Tests for encrypted secrets module."""

from __future__ import annotations

import pytest

from src.security.secrets import SecretManager


class TestSecretManager:
    """Test encrypted secrets storage."""

    def test_encrypt_decrypt_string(self) -> None:
        mgr = SecretManager(master_key="test-key-123")
        plaintext = "my-secret-api-key"
        encrypted = mgr.encrypt(plaintext)
        assert encrypted != plaintext
        decrypted = mgr.decrypt(encrypted)
        assert decrypted == plaintext

    def test_encrypt_decrypt_dict(self) -> None:
        mgr = SecretManager(master_key="test-key-123")
        data = {"api_key": "sk-123", "secret": "password"}
        encrypted = mgr.encrypt_dict(data)
        assert encrypted != str(data)
        decrypted = mgr.decrypt_dict(encrypted)
        assert decrypted == data

    def test_different_encryptions_different_ciphertext(self) -> None:
        mgr = SecretManager(master_key="test-key-123")
        enc1 = mgr.encrypt("same-plaintext")
        enc2 = mgr.encrypt("same-plaintext")
        # Each encryption uses random salt, so ciphertexts differ
        assert enc1 != enc2

    def test_default_master_key_warning(self) -> None:
        # Just verify it doesn't crash with default key
        mgr = SecretManager()
        encrypted = mgr.encrypt("test")
        decrypted = mgr.decrypt(encrypted)
        assert decrypted == "test"

    def test_xor_fallback(self) -> None:
        """Test XOR fallback when cryptography is not available."""
        mgr = SecretManager(master_key="test-key")
        # Directly test the fallback methods
        encrypted = mgr._xor_obfuscate("test-value")
        decrypted = mgr._xor_deobfuscate(encrypted)
        assert decrypted == "test-value"
        assert encrypted != "test-value"
