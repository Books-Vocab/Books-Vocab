from __future__ import annotations

from kg.secret_store import decrypt_value, encrypt_value, is_encrypted
from kg.user_store import normalize_users_payload, resolve_mochi_api_key_from_config


_SECRET = "test-jwt-secret-key"


def _default_subscription():
    return {
        "is_active": False,
        "status": "inactive",
        "plan_name": None,
        "trial_days": 7,
        "will_renew": False,
    }


class TestEncryptDecryptRoundtrip:

    def test_roundtrip(self):
        plaintext = "my-mochi-api-key-abc123"
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


class TestNormalizeUsersEncryption:

    def test_plain_key_gets_encrypted_when_encrypt_fn_provided(self):
        users = {
            "user1": {
                "config": {
                    "integrations": {
                        "mochi": {"api_key": "plain-key-abc"}
                    }
                }
            }
        }
        encrypt_fn = lambda v: encrypt_value(v, _SECRET)
        result, changed = normalize_users_payload(users, _default_subscription, encrypt_fn=encrypt_fn)

        stored_key = result["user1"]["config"]["integrations"]["mochi"]["api_key"]
        assert is_encrypted(stored_key)
        assert changed

    def test_already_encrypted_key_not_double_encrypted(self):
        already_encrypted = encrypt_value("plain-key", _SECRET)
        users = {
            "user1": {
                "config": {
                    "integrations": {
                        "mochi": {"api_key": already_encrypted}
                    }
                }
            }
        }
        encrypt_fn = lambda v: encrypt_value(v, _SECRET)
        result, _ = normalize_users_payload(users, _default_subscription, encrypt_fn=encrypt_fn)

        stored_key = result["user1"]["config"]["integrations"]["mochi"]["api_key"]
        assert stored_key == already_encrypted
        assert decrypt_value(stored_key, _SECRET) == "plain-key"

    def test_no_encrypt_fn_leaves_key_as_is(self):
        users = {
            "user1": {
                "config": {
                    "integrations": {
                        "mochi": {"api_key": "plain-key"}
                    }
                }
            }
        }
        result, _ = normalize_users_payload(users, _default_subscription, encrypt_fn=None)

        stored_key = result["user1"]["config"]["integrations"]["mochi"]["api_key"]
        assert stored_key == "plain-key"


class TestResolveMochiApiKeyDecrypts:

    def test_resolve_decrypts_encrypted_key(self):
        plaintext = "actual-mochi-key"
        encrypted = encrypt_value(plaintext, _SECRET)
        config = {"integrations": {"mochi": {"api_key": encrypted}}}
        result = resolve_mochi_api_key_from_config(config, _SECRET)
        assert result == plaintext

    def test_resolve_returns_plaintext_when_no_jwt_secret(self):
        config = {"integrations": {"mochi": {"api_key": "plain-key"}}}
        result = resolve_mochi_api_key_from_config(config, "")
        assert result == "plain-key"

    def test_resolve_returns_none_when_no_key(self):
        assert resolve_mochi_api_key_from_config({}) is None
