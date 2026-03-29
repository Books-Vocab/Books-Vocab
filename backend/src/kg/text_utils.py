"""Shared text normalization utilities."""
import unicodedata


def normalize_nfc(text: str) -> str:
    """NFC normalize + strip. For content identity checks."""
    return unicodedata.normalize("NFC", text).strip()


def normalize_nfc_lower(text: str) -> str:
    """NFC normalize + strip + lower. For case-insensitive matching."""
    return unicodedata.normalize("NFC", text).strip().lower()
