"""Provider selection plus the shared retry / JSON-parsing helpers.

`LLM_PROVIDER` env var picks the backend (default "anthropic"). The retry helpers
centralize the [3, 8, 15]s schedule that all three call sites previously
duplicated, and translate the common LLM* errors into user-facing messages.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time

from app.llm.base import (
    LLMAuthError,
    LLMBadRequestError,
    LLMError,
    LLMOverloadedError,
    LLMProvider,
    LLMRateLimitError,
    LLMResponse,
)

logger = logging.getLogger(__name__)

_RETRY_DELAYS = [3, 8, 15]  # seconds before each successive retry

# Supported provider keys, in the order the UI toggle should present them.
AVAILABLE_PROVIDERS: tuple[str, ...] = ("anthropic", "ollama")

_provider: LLMProvider | None = None
_provider_key: str | None = None

# Runtime override set via the UI toggle (POST /api/provider). When None, the
# LLM_PROVIDER env var (default "anthropic") decides. The override lives in
# process memory only — it is not persisted across restarts.
_override_key: str | None = None


def _active_key() -> str:
    """The provider key currently in effect: runtime override wins over env."""
    if _override_key is not None:
        return _override_key
    return os.getenv("LLM_PROVIDER", "anthropic").strip().lower()


def get_provider() -> LLMProvider:
    """Return the configured provider singleton, rebuilding if the active key changed."""
    global _provider, _provider_key
    key = _active_key()
    if _provider is None or _provider_key != key:
        _provider = _build_provider(key)
        _provider_key = key
    return _provider


def set_provider(key: str) -> LLMProvider:
    """Override the active provider at runtime (used by the UI toggle).

    Raises ValueError for an unsupported key. Returns the now-active provider.
    """
    global _override_key
    key = key.strip().lower()
    if key not in AVAILABLE_PROVIDERS:
        raise ValueError(
            f"Unknown provider '{key}'. Supported values: {', '.join(AVAILABLE_PROVIDERS)}."
        )
    _override_key = key
    return get_provider()


def _build_provider(key: str) -> LLMProvider:
    if key == "anthropic":
        from app.llm.anthropic_provider import AnthropicProvider

        return AnthropicProvider()
    if key == "ollama":
        from app.llm.ollama_provider import OllamaProvider

        return OllamaProvider()
    raise ValueError(
        f"Unknown LLM_PROVIDER '{key}'. Supported values: 'anthropic', 'ollama'."
    )


def reset_provider_cache() -> None:
    """Clear the cached provider and runtime override — used by tests that flip LLM_PROVIDER."""
    global _provider, _provider_key, _override_key
    _provider = None
    _provider_key = None
    _override_key = None


# ── Retry helpers ─────────────────────────────────────────────────────────────


def _friendly_terminal_error(exc: LLMError) -> ValueError:
    """Map a non-retryable error to the user-facing message."""
    if isinstance(exc, LLMAuthError):
        return ValueError(str(exc))
    if isinstance(exc, LLMBadRequestError):
        return ValueError(f"The LLM rejected the request: {exc}")
    return ValueError(str(exc))


async def acomplete_with_retry(provider: LLMProvider, **kwargs) -> LLMResponse:
    """Async completion with the shared retry schedule on overload/rate-limit."""
    for attempt in range(len(_RETRY_DELAYS) + 1):
        try:
            return await provider.acomplete(**kwargs)
        except (LLMAuthError, LLMBadRequestError) as exc:
            raise _friendly_terminal_error(exc) from exc
        except (LLMOverloadedError, LLMRateLimitError) as exc:
            if attempt < len(_RETRY_DELAYS):
                delay = _RETRY_DELAYS[attempt]
                logger.warning(
                    "%s busy (attempt %d/%d), retrying in %ds… (%s)",
                    provider.name, attempt + 1, len(_RETRY_DELAYS) + 1, delay, exc,
                )
                await asyncio.sleep(delay)
                continue
            raise ValueError(
                "The LLM is temporarily busy or rate-limited. Please wait a moment and try again."
            ) from exc
        except LLMError as exc:
            if attempt == 0:
                await asyncio.sleep(3)
                continue
            raise ValueError(str(exc)) from exc
    raise ValueError("LLM request failed after retries.")  # pragma: no cover


def complete_with_retry(provider: LLMProvider, **kwargs) -> LLMResponse:
    """Synchronous counterpart of acomplete_with_retry."""
    for attempt in range(len(_RETRY_DELAYS) + 1):
        try:
            return provider.complete(**kwargs)
        except (LLMAuthError, LLMBadRequestError) as exc:
            raise _friendly_terminal_error(exc) from exc
        except (LLMOverloadedError, LLMRateLimitError) as exc:
            if attempt < len(_RETRY_DELAYS):
                delay = _RETRY_DELAYS[attempt]
                logger.warning(
                    "%s busy (attempt %d/%d), retrying in %ds… (%s)",
                    provider.name, attempt + 1, len(_RETRY_DELAYS) + 1, delay, exc,
                )
                time.sleep(delay)
                continue
            raise ValueError(
                "The LLM is temporarily busy or rate-limited. Please wait a moment and try again."
            ) from exc
        except LLMError as exc:
            if attempt == 0:
                time.sleep(3)
                continue
            raise ValueError(str(exc)) from exc
    raise ValueError("LLM request failed after retries.")  # pragma: no cover


# ── Shared JSON parsing ───────────────────────────────────────────────────────


def parse_json_response(raw_text: str) -> dict:
    """Parse an LLM JSON reply, tolerating ```json fenced blocks."""
    text = raw_text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        inner = lines[1:] if lines else []
        if inner and inner[-1].strip() == "```":
            inner = inner[:-1]
        text = "\n".join(inner).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"The LLM returned invalid JSON: {raw_text[:300]}") from exc
