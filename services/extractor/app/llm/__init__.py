"""Provider-agnostic LLM layer. The provider is chosen by LLM_PROVIDER (or per request), never in workflows."""
from __future__ import annotations

from .base import LLMError, LLMResult, Provider  # noqa: F401


def get_provider(name: str) -> Provider:
    name = (name or "rules").lower()
    if name == "rules":
        from .rules import RulesProvider
        return RulesProvider()
    if name in ("gigachat", "yandex", "openai"):
        from .openai_compat import make
        return make(name)
    raise LLMError(f"unknown LLM provider {name!r}")
