from __future__ import annotations

import pytest

from kg.secret_store import decrypt_value, encrypt_value, is_encrypted

_SECRET = "test-jwt-secret-key"


@pytest.fixture(autouse=True)
def _clear_secret_enc_key(monkeypatch):
    """每個測試預設無 SECRET_ENC_KEY，確保彼此隔離。"""
    monkeypatch.delenv("SECRET_ENC_KEY", raising=False)


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


class TestSecretEncKeyDecoupling:
    """SECRET_ENC_KEY 解除「加密金鑰 ←→ JWT_SECRET」耦合。"""

    def test_no_enc_key_matches_legacy_behavior(self, monkeypatch):
        # 未設 SECRET_ENC_KEY → 與改前完全一致（既有 enc: 值可解）
        monkeypatch.delenv("SECRET_ENC_KEY", raising=False)
        enc = encrypt_value("legacy-val", _SECRET)
        assert decrypt_value(enc, _SECRET) == "legacy-val"

    def test_enc_key_used_for_encryption(self, monkeypatch):
        # 設了 SECRET_ENC_KEY → 用它加解密；jwt_secret 不再是加密根
        monkeypatch.setenv("SECRET_ENC_KEY", "independent-enc-root-key-32")
        enc = encrypt_value("v", _SECRET)
        # 同一 SECRET_ENC_KEY、但完全不同的 jwt_secret 仍可解密
        assert decrypt_value(enc, "totally-different-jwt-secret!!") == "v"

    def test_legacy_value_still_decryptable_after_jwt_rotation(self, monkeypatch):
        # 舊值用 legacy sha256(JWT_SECRET) 加密（無 SECRET_ENC_KEY 時期）
        monkeypatch.delenv("SECRET_ENC_KEY", raising=False)
        legacy_enc = encrypt_value("old-secret", _SECRET)
        # 之後導入 SECRET_ENC_KEY；舊值仍須能經 fallback 解出
        monkeypatch.setenv("SECRET_ENC_KEY", "new-independent-enc-root-key")
        assert decrypt_value(legacy_enc, _SECRET) == "old-secret"

    def test_new_value_unaffected_by_jwt_rotation(self, monkeypatch):
        # 設 SECRET_ENC_KEY 後新寫入；輪換 JWT_SECRET 不影響其解密
        monkeypatch.setenv("SECRET_ENC_KEY", "stable-enc-root-key-value")
        enc = encrypt_value("new-secret", "jwt-before-rotation")
        assert decrypt_value(enc, "jwt-AFTER-rotation-changed!!") == "new-secret"

    def test_enc_key_set_can_still_decrypt_legacy_then_reencrypt_uses_enc_key(
        self, monkeypatch
    ):
        # 平滑遷移：設了 SECRET_ENC_KEY，legacy 值解得出，新加密用當前 key
        monkeypatch.delenv("SECRET_ENC_KEY", raising=False)
        legacy_enc = encrypt_value("val", _SECRET)
        monkeypatch.setenv("SECRET_ENC_KEY", "enc-root-key-for-migration")
        plain = decrypt_value(legacy_enc, _SECRET)
        re_enc = encrypt_value(plain, _SECRET)
        # 新密文用 SECRET_ENC_KEY 加密 → 改 jwt_secret 不影響
        assert decrypt_value(re_enc, "any-other-jwt") == "val"


class TestIsEncrypted:

    def test_encrypted_value(self):
        assert is_encrypted("enc:AAABBBCCC")

    def test_plain_value(self):
        assert not is_encrypted("plain-api-key")

    def test_empty_string(self):
        assert not is_encrypted("")
