from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from kg.api_models.common import _normalize_context
from kg.languages import SUPPORTED_SOURCE_LANGS, SUPPORTED_TARGET_LANGS


class TranslationLanguageConfig(BaseModel):
    source_lang: str = "en"
    target_lang: str = "zh-Hant"

    @field_validator("source_lang")
    @classmethod
    def validate_source_lang(cls, v: str) -> str:
        if v not in SUPPORTED_SOURCE_LANGS:
            raise ValueError(f"Unsupported source language: {v}")
        return v

    @field_validator("target_lang")
    @classmethod
    def validate_target_lang(cls, v: str) -> str:
        if v not in SUPPORTED_TARGET_LANGS:
            raise ValueError(f"Unsupported target language: {v}")
        return v


class TranslateRequest(BaseModel):
    word: str = Field(min_length=1, max_length=500)
    context: str = Field(default="", max_length=1000)
    source_lang: str | None = None
    target_lang: str | None = None

    @field_validator("context", mode="before")
    @classmethod
    def normalize_context(cls, v: str) -> str:
        if isinstance(v, str):
            v = _normalize_context(v)
            if len(v) > 1000:
                v = v[:1000]
        return v

    @field_validator("source_lang")
    @classmethod
    def validate_source_lang(cls, v: str | None) -> str | None:
        if v is not None and v not in SUPPORTED_SOURCE_LANGS:
            raise ValueError(f"Unsupported source language: {v}")
        return v

    @field_validator("target_lang")
    @classmethod
    def validate_target_lang(cls, v: str | None) -> str | None:
        if v is not None and v not in SUPPORTED_TARGET_LANGS:
            raise ValueError(f"Unsupported target language: {v}")
        return v


class QuickTranslateResponse(BaseModel):
    t: str
    p: str | None = None
    r: str | None = None  # root form (lemma)


class ExplainResponse(BaseModel):
    e: str


class PhraseTranslateResponse(BaseModel):
    t: str
