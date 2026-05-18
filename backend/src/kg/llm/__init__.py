"""Pluggable LLM provider layer.

All providers (Gemini, DeepSeek, future Qwen/GLM) speak the OpenAI-compatible
API, so a provider is configuration, not code — see `providers.py`.
"""
from .providers import REGISTRY, LLMProvider, provider_for

__all__ = ["REGISTRY", "LLMProvider", "provider_for"]
