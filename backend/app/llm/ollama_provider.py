"""Ollama (local, open-source models) implementation of the LLMProvider interface.

Talks to a local Ollama server's /api/chat endpoint over httpx. No API key is
required. For vision tasks (/analyze) the configured model must be multimodal
(e.g. llama3.2-vision); text-only models work for instructions and piece fallback.
"""
from __future__ import annotations

import base64
import os

import httpx

from app.llm.base import (
    LLMBadRequestError,
    LLMError,
    LLMOverloadedError,
    LLMProvider,
    LLMResponse,
)

_DEFAULT_BASE_URL = "http://localhost:11434"
# Qwen2.5-VL is a strong, widely-compatible vision model that follows JSON
# instructions well. (llama3.2-vision is better in theory but its 'mllama'
# architecture fails to load on some Ollama builds.)
_DEFAULT_MODEL = "qwen2.5vl:7b"
# Generous ceiling — local generation can be slow on CPU-only hosts.
_TIMEOUT = httpx.Timeout(300.0, connect=10.0)


class OllamaProvider(LLMProvider):
    def __init__(self) -> None:
        self._base_url = os.getenv("OLLAMA_BASE_URL", _DEFAULT_BASE_URL).rstrip("/")
        self._model = os.getenv("OLLAMA_MODEL", _DEFAULT_MODEL)

    @property
    def name(self) -> str:
        return "ollama"

    @property
    def model(self) -> str:
        return self._model

    def _build_payload(
        self,
        system: str,
        user_text: str,
        max_tokens: int,
        images: list[bytes] | None,
        response_format: dict | None = None,
        temperature: float | None = None,
    ) -> dict:
        user_message: dict = {"role": "user", "content": user_text}
        if images:
            user_message["images"] = [base64.standard_b64encode(b).decode() for b in images]
        options: dict = {"num_predict": max_tokens}
        if temperature is not None:
            # Low temperature + tight top_p curbs the hallucination/invention a
            # small local model is prone to during structured extraction.
            options["temperature"] = temperature
            options["top_p"] = 0.5
        payload: dict = {
            "model": self._model,
            "stream": False,
            "messages": [
                {"role": "system", "content": system},
                user_message,
            ],
            "options": options,
        }
        if response_format is not None:
            # Ollama structured outputs: a JSON Schema in `format` constrains
            # decoding so the model cannot emit out-of-enum or malformed JSON.
            payload["format"] = response_format
        return payload

    def _parse(self, data: dict) -> LLMResponse:
        return LLMResponse(
            text=data.get("message", {}).get("content", ""),
            truncated=data.get("done_reason") == "length",
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
        payload = self._build_payload(
            system, user_text, max_tokens, images, response_format, temperature
        )
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.post(f"{self._base_url}/api/chat", json=payload)
        except (httpx.ConnectError, httpx.TimeoutException) as exc:
            raise LLMOverloadedError(_unreachable_msg(self._base_url)) from exc
        return self._handle(resp)

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
        payload = self._build_payload(
            system, user_text, max_tokens, images, response_format, temperature
        )
        try:
            with httpx.Client(timeout=_TIMEOUT) as client:
                resp = client.post(f"{self._base_url}/api/chat", json=payload)
        except (httpx.ConnectError, httpx.TimeoutException) as exc:
            raise LLMOverloadedError(_unreachable_msg(self._base_url)) from exc
        return self._handle(resp)

    def _handle(self, resp: httpx.Response) -> LLMResponse:
        if resp.status_code == 404:
            # Ollama returns 404 when the requested model isn't pulled.
            raise LLMBadRequestError(
                f"Ollama model '{self._model}' was not found. Run `ollama pull {self._model}` first."
            )
        if resp.status_code >= 400:
            raise LLMError(f"Ollama request failed ({resp.status_code}): {resp.text[:200]}")
        return self._parse(resp.json())


def _unreachable_msg(base_url: str) -> str:
    return (
        f"Could not reach the Ollama server at {base_url}. "
        "Make sure Ollama is running (`ollama serve`) and OLLAMA_BASE_URL is correct."
    )
