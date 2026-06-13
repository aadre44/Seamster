"""Provider-agnostic LLM layer for Seamster.

Supports Anthropic Claude (default) and a local Ollama server, selected via the
LLM_PROVIDER environment variable. Call sites build prompts and validate output;
this package handles client setup, the request shape, retries, and JSON parsing.
"""
from app.llm.base import (
    LLMAuthError,
    LLMBadRequestError,
    LLMError,
    LLMOverloadedError,
    LLMProvider,
    LLMRateLimitError,
    LLMResponse,
)
from app.llm.factory import (
    AVAILABLE_PROVIDERS,
    acomplete_with_retry,
    complete_with_retry,
    get_provider,
    parse_json_response,
    reset_provider_cache,
    set_provider,
)

__all__ = [
    "AVAILABLE_PROVIDERS",
    "LLMAuthError",
    "LLMBadRequestError",
    "LLMError",
    "LLMOverloadedError",
    "LLMProvider",
    "LLMRateLimitError",
    "LLMResponse",
    "acomplete_with_retry",
    "complete_with_retry",
    "get_provider",
    "parse_json_response",
    "reset_provider_cache",
    "set_provider",
]
