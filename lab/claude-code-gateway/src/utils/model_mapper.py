from __future__ import annotations

ALIASES = {"sonnet", "opus", "haiku"}

MODEL_MAP: dict[str, str] = {
    "gpt-4": "sonnet",
    "gpt-4o": "sonnet",
    "gpt-4-turbo": "sonnet",
    "gpt-3.5-turbo": "haiku",
    "gpt-4o-mini": "haiku",
}

AVAILABLE_MODELS: list[dict[str, str]] = [
    {"id": "sonnet", "name": "Claude Sonnet (latest)"},
    {"id": "opus", "name": "Claude Opus (latest)"},
    {"id": "haiku", "name": "Claude Haiku (latest)"},
]


def resolve_model(model: str) -> str:
    """Resolve to CLI-native alias. CLI handles version mapping automatically."""
    if model in ALIASES:
        return model
    return MODEL_MAP.get(model, model)
