"""Anthropic Claude implementation of the LLMProvider interface."""
from __future__ import annotations

import base64
import os

import anthropic

from app.llm.base import (
    LLMAuthError,
    LLMBadRequestError,
    LLMError,
    LLMOverloadedError,
    LLMProvider,
    LLMRateLimitError,
    LLMResponse,
)

_DEFAULT_MODEL = "claude-sonnet-4-6"


def _media_type(img_bytes: bytes) -> str:
    if img_bytes[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if img_bytes[:4] == b"GIF8":
        return "image/gif"
    if img_bytes[:4] == b"RIFF" and img_bytes[8:12] == b"WEBP":
        return "image/webp"
    return "image/jpeg"  # default / JPEG magic \xff\xd8


def _build_content(user_text: str, images: list[bytes] | None) -> list:
    content: list = []
    for img_bytes in images or []:
        b64 = base64.standard_b64encode(img_bytes).decode()
        content.append({
            "type": "image",
            "source": {"type": "base64", "media_type": _media_type(img_bytes), "data": b64},
        })
    content.append({"type": "text", "text": user_text})
    return content


class AnthropicProvider(LLMProvider):
    def __init__(self) -> None:
        self._model = os.getenv("CLAUDE_MODEL", _DEFAULT_MODEL)
        self._async_client: anthropic.AsyncAnthropic | None = None
        self._sync_client: anthropic.Anthropic | None = None

    @property
    def name(self) -> str:
        return "anthropic"

    @property
    def model(self) -> str:
        return self._model

    def _api_key(self) -> str:
        key = os.getenv("ANTHROPIC_API_KEY")
        if not key:
            raise LLMAuthError(
                "Anthropic API key is missing. Check your ANTHROPIC_API_KEY environment variable."
            )
        return key

    def _aclient(self) -> anthropic.AsyncAnthropic:
        if self._async_client is None:
            self._async_client = anthropic.AsyncAnthropic(api_key=self._api_key())
        return self._async_client

    def _client(self) -> anthropic.Anthropic:
        if self._sync_client is None:
            self._sync_client = anthropic.Anthropic(api_key=self._api_key())
        return self._sync_client

    def _to_response(self, response) -> LLMResponse:
        return LLMResponse(
            text=response.content[0].text,
            truncated=response.stop_reason == "max_tokens",
        )

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
        # `response_format` (JSON-Schema constrained decoding) is an Ollama-only
        # feature; Claude follows the schema described in the prompt, so we
        # accept the arg for interface parity and ignore it here.
        try:
            response = await self._aclient().messages.create(
                **self._create_kwargs(system, user_text, max_tokens, images, temperature)
            )
        except anthropic.APIError as exc:
            raise _map_error(exc) from exc
        return self._to_response(response)

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
        try:
            response = self._client().messages.create(
                **self._create_kwargs(system, user_text, max_tokens, images, temperature)
            )
        except anthropic.APIError as exc:
            raise _map_error(exc) from exc
        return self._to_response(response)

    def _create_kwargs(
        self,
        system: str,
        user_text: str,
        max_tokens: int,
        images: list[bytes] | None,
        temperature: float | None,
    ) -> dict:
        kwargs: dict = {
            "model": self._model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": _build_content(user_text, images)}],
        }
        if temperature is not None:
            kwargs["temperature"] = temperature
        return kwargs


def _map_error(exc: anthropic.APIError) -> LLMError:
    """Translate an Anthropic SDK error into the common LLM* hierarchy."""
    if isinstance(exc, anthropic.AuthenticationError):
        return LLMAuthError(
            "Anthropic API key is missing or invalid. Check your ANTHROPIC_API_KEY environment variable."
        )
    if isinstance(exc, anthropic.BadRequestError):
        return LLMBadRequestError(str(exc))
    if isinstance(exc, anthropic.OverloadedError):
        return LLMOverloadedError(str(exc))
    if isinstance(exc, anthropic.RateLimitError):
        return LLMRateLimitError(str(exc))
    return LLMError(str(exc))
