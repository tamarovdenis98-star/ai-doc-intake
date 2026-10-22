from __future__ import annotations

from dataclasses import dataclass, field


class LLMError(Exception):
    """Provider call failed (HTTP, auth, unparseable answer). retryable=True for 429/5xx/timeouts."""

    def __init__(self, message: str, retryable: bool = False):
        super().__init__(message)
        self.retryable = retryable


@dataclass
class LLMResult:
    content: dict
    provider: str
    model: str
    tokens_in: int = 0
    tokens_out: int = 0
    duration_ms: int = 0
    raw: str = field(default="", repr=False)


class Provider:
    name = "base"
    model = ""

    def complete_json(self, task: str, system: str, user: str, schema: dict, max_tokens: int) -> LLMResult:
        """task: 'classify' | 'extract' | 'repair'. Must return a JSON object (validated by the caller)."""
        raise NotImplementedError
