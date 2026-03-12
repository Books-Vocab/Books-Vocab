"""Shared language constants."""

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

SUPPORTED_SOURCE_LANGS: set[str] = {"en", "ja", "ko", "fr", "de", "es"}
SUPPORTED_TARGET_LANGS: set[str] = {"zh-Hant", "zh-Hans", "en", "ja", "ko"}
