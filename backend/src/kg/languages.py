"""Shared language constants."""

from typing import Final

LANGUAGE_NAMES: dict[str, str] = {
    "en": "English",
    "ja": "Japanese",
    "ko": "Korean",
    "fr": "French",
    "de": "German",
    "es": "Spanish",
    "zh-Hant": "Traditional Chinese",
    "zh-Hans": "Simplified Chinese",
}

SUPPORTED_SOURCE_LANGS: Final[frozenset[str]] = frozenset({"en", "ja", "ko", "fr", "de", "es"})
SUPPORTED_TARGET_LANGS: Final[frozenset[str]] = frozenset({"zh-Hant", "zh-Hans", "en", "ja", "ko"})
