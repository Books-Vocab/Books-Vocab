from __future__ import annotations

from kg.secret_store import decrypt_value, encrypt_value, is_encrypted


_SECRET = "test-jwt-secret-key"


class TestEncryptDecryptRoundtrip:

    def test_roundtrip(self):
        plaintext = "my-secret-value-abc123"
        encrypted = encrypt_value(plaintext, _SECRET)
        assert encrypted != plaintext
        assert is_encrypted(encrypted)
        assert decrypt_value(encrypted, _SECRET) == plaintext

    def test_different_secrets_produce_different_ciphertext(self):
        enc_a = encrypt_value("hello", "secret-a")
        enc_b = encrypt_value("hello", "secret-b")
        assert enc_a != enc_b

    def test_each_encryption_produces_unique_ciphertext(self):
        enc1 = encrypt_value("hello", _SECRET)
        enc2 = encrypt_value("hello", _SECRET)
        # Fernet uses random IV — same plaintext should produce different ciphertext
        assert enc1 != enc2
        assert decrypt_value(enc1, _SECRET) == "hello"
        assert decrypt_value(enc2, _SECRET) == "hello"


class TestBackwardCompatibility:

    def test_decrypt_plaintext_returns_as_is(self):
        plaintext = "plain-key-no-prefix"
        assert decrypt_value(plaintext, _SECRET) == plaintext

    def test_decrypt_empty_jwt_secret_returns_stored(self):
        # empty jwt_secret → return encrypted value as-is
        encrypted = encrypt_value("mykey", _SECRET)
        result = decrypt_value(encrypted, "")
        assert result == encrypted  # can't decrypt without secret

    def test_decrypt_wrong_key_raises_valueerror(self):
        encrypted = encrypt_value("mykey", _SECRET)
        import pytest
        with pytest.raises(ValueError, match="key mismatch"):
            decrypt_value(encrypted, "wrong-secret-key!!")


class TestIsEncrypted:

    def test_encrypted_value(self):
        assert is_encrypted("enc:AAABBBCCC")

    def test_plain_value(self):
        assert not is_encrypted("plain-api-key")

    def test_empty_string(self):
        assert not is_encrypted("")
