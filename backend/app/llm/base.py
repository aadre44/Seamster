"""Provider-agnostic LLM interface shared by all Seamster AI call sites.

Each call site (vision analysis, instruction generation, novel-piece fallback)
constructs its own prompt and validates its own output. Only the client
instantiation, request shape, and error surface are unified here so the backend
can swap between Anthropic Claude and a local Ollama server via configuration.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class LLMResponse:
    """Normalized result of a single completion call."""

    text: str
    # True when the model stopped because it hit the token cap (Anthropic
    # stop_reason == "max_tokens" / Ollama done_reason == "length"). Call sites
    # use this to warn that output was cut off instead of silently truncating.
    truncated: bool = False


# ── Common error hierarchy ────────────────────────────────────────────────────
# Each provider maps its native exceptions onto these so the shared retry helper
# in factory.py can react uniformly regardless of which backend is active.


class LLMError(Exception):
    """Base for all provider errors (also used for connection failures)."""


class LLMAuthError(LLMError):
    """Missing or invalid credentials."""


class LLMBadRequestError(LLMError):
    """The provider rejected the request as malformed/unsupported."""


class LLMRateLimitError(LLMError):
    """Rate limit reached — retryable after a short wait."""


class LLMOverloadedError(LLMError):
    """Provider temporarily overloaded/unreachable — retryable after a wait."""


class LLMProvider(ABC):
    """A text+vision completion backend.

    `images` are raw image bytes; each provider performs its own base64 encoding
    and media-type detection. Implementations must map their native errors onto
    the LLM* exception hierarchy above.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Short provider identifier, e.g. 'anthropic' or 'ollama'."""

    @property
    @abstractmethod
    def model(self) -> str:
        """The model id this provider is currently configured to use."""

    @abstractmethod
    async def acomplete(
        self,
        *,
        system: str,
        user_text: str,
        max_tokens: int,
        images: list[bytes] | None = None,
        response_format: dict | None = None,
        temperature: float | None = None,
    ) -> LLMResponse:
        """Async completion.

        `response_format` is an optional JSON Schema for constrained decoding.
        Providers that support it (Ollama) force the output to match the schema;
        those that don't (Anthropic) ignore it. `temperature` overrides the
        provider default when set — pass 0 for deterministic extraction.
        """

    @abstractmethod
    def complete(
        self,
        *,
        system: str,
        user_text: str,
        max_tokens: int,
        images: list[bytes] | None = None,
        response_format: dict | None = None,
        temperature: float | None = None,
    ) -> LLMResponse:
        """Synchronous completion. See `acomplete` for parameter semantics."""
