"""Stored-secret 對稱加密。

加密根金鑰來源（解除「加密金鑰 ←→ JWT_SECRET」耦合）：

- **`SECRET_ENC_KEY` env var 已設** → 用 `sha256(SECRET_ENC_KEY)` 派生 Fernet key。
  此時加密與 JWT_SECRET 完全脫鉤：輪換 JWT_SECRET 不影響任何 stored secret 的
  解密（也不需 re-encrypt migration）。
- **`SECRET_ENC_KEY` 未設** → fallback 到 legacy 行為 `sha256(JWT_SECRET)`。
  既有部署零破壞，既有 `enc:` 值仍可正常解密。

解密採多金鑰容錯（平滑遷移）：先試「當前 key」，失敗再試 legacy
`sha256(JWT_SECRET)`。這讓「已設 SECRET_ENC_KEY、但舊值仍是用 JWT_SECRET 加密」
的過渡期不中斷服務 —— 無需強制 re-encrypt 即可上線（migration 為可選、另案）。
**新寫入一律用當前 key**（SECRET_ENC_KEY 優先），不弱化加密強度。
"""

import base64
import hashlib
import os

from cryptography.fernet import Fernet, InvalidToken, MultiFernet


def _sha256_fernet_key(material: str) -> bytes:
    """從任意字串材料衍生固定、可重複的 Fernet key。"""
    digest = hashlib.sha256(material.encode()).digest()
    return base64.urlsafe_b64encode(digest)


def _enc_key_material() -> str | None:
    """當前加密根金鑰材料：SECRET_ENC_KEY env var（未設則 None → fallback）。"""
    raw = os.getenv("SECRET_ENC_KEY")
    if raw is None:
        return None
    raw = raw.strip()
    return raw or None


def _current_fernet(jwt_secret: str) -> Fernet:
    """新寫入使用的當前 Fernet：SECRET_ENC_KEY 優先，否則 legacy sha256(JWT_SECRET)。"""
    material = _enc_key_material() or jwt_secret
    return Fernet(_sha256_fernet_key(material))


def _decrypt_fernet(jwt_secret: str) -> MultiFernet:
    """解密用 MultiFernet：當前 key 先試，失敗再退回 legacy sha256(JWT_SECRET)。

    當 SECRET_ENC_KEY 未設時，當前 key 與 legacy key 相同（皆來自 jwt_secret），
    MultiFernet 退化為單 key，行為與改前一致。
    """
    keys: list[Fernet] = []
    material = _enc_key_material()
    if material is not None:
        keys.append(Fernet(_sha256_fernet_key(material)))
    # legacy / fallback：sha256(JWT_SECRET)
    keys.append(Fernet(_sha256_fernet_key(jwt_secret)))
    return MultiFernet(keys)


def encrypt_value(plaintext: str, jwt_secret: str) -> str:
    """加密並回傳 'enc:' prefix 標記的密文（使用當前加密根金鑰）。"""
    f = _current_fernet(jwt_secret)
    return "enc:" + f.encrypt(plaintext.encode()).decode()


def decrypt_value(stored: str, jwt_secret: str) -> str:
    """解密 'enc:' prefix 的密文。若無 prefix 則視為明文（向後相容）。

    多金鑰容錯：先試當前 key（SECRET_ENC_KEY），失敗退回 legacy sha256(JWT_SECRET)。
    """
    if not stored.startswith("enc:"):
        return stored  # 未加密的舊值，向後相容
    if not jwt_secret and _enc_key_material() is None:
        return stored  # 無任何可用金鑰時原樣回傳
    try:
        f = _decrypt_fernet(jwt_secret)
        return f.decrypt(stored[4:].encode()).decode()
    except InvalidToken as exc:
        raise ValueError(
            "Cannot decrypt stored secret: key mismatch. "
            "Tried SECRET_ENC_KEY (if set) and legacy sha256(JWT_SECRET). "
            "Was SECRET_ENC_KEY changed, or JWT_SECRET rotated without an "
            "independent SECRET_ENC_KEY set? Re-encrypt stored secrets with "
            "the current key."
        ) from exc


def is_encrypted(value: str) -> bool:
    return value.startswith("enc:")
