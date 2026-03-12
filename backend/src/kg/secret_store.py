import base64
import hashlib
from cryptography.fernet import Fernet, InvalidToken


def _derive_key(jwt_secret: str) -> bytes:
    """從 JWT_SECRET 衍生 Fernet 密鑰（固定、可重複）。"""
    digest = hashlib.sha256(jwt_secret.encode()).digest()
    return base64.urlsafe_b64encode(digest)


def encrypt_value(plaintext: str, jwt_secret: str) -> str:
    """加密並回傳 'enc:' prefix 標記的密文。"""
    f = Fernet(_derive_key(jwt_secret))
    return "enc:" + f.encrypt(plaintext.encode()).decode()


def decrypt_value(stored: str, jwt_secret: str) -> str:
    """解密 'enc:' prefix 的密文。若無 prefix 則視為明文（向後相容）。"""
    if not stored.startswith("enc:"):
        return stored  # 未加密的舊值，向後相容
    f = Fernet(_derive_key(jwt_secret))
    return f.decrypt(stored[4:].encode()).decode()


def is_encrypted(value: str) -> bool:
    return value.startswith("enc:")
