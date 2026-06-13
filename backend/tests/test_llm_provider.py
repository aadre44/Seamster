"""Tests for the provider-agnostic LLM layer (factory, Ollama provider, helpers)."""
import httpx
import pytest

from app.llm import (
    LLMOverloadedError,
    parse_json_response,
    reset_provider_cache,
)
from app.llm.anthropic_provider import AnthropicProvider
from app.llm.base import LLMAuthError, LLMResponse
from app.llm.factory import acomplete_with_retry, get_provider, set_provider
from app.llm.ollama_provider import OllamaProvider


@pytest.fixture(autouse=True)
def _clear_cache():
    reset_provider_cache()
    yield
    reset_provider_cache()


# ── Provider selection ────────────────────────────────────────────────────────

def test_get_provider_defaults_to_anthropic(monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    assert isinstance(get_provider(), AnthropicProvider)


def test_get_provider_ollama(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    provider = get_provider()
    assert isinstance(provider, OllamaProvider)
    assert provider.name == "ollama"


def test_get_provider_is_case_insensitive(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "Anthropic")
    assert isinstance(get_provider(), AnthropicProvider)


def test_get_provider_unknown_raises(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "gpt5")
    with pytest.raises(ValueError, match="Unknown LLM_PROVIDER"):
        get_provider()


def test_get_provider_rebuilds_on_change(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    first = get_provider()
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    second = get_provider()
    assert first is not second
    assert isinstance(second, OllamaProvider)


# ── Runtime override (UI toggle) ──────────────────────────────────────────────

def test_set_provider_overrides_env(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    assert isinstance(get_provider(), AnthropicProvider)
    set_provider("ollama")
    assert isinstance(get_provider(), OllamaProvider)


def test_set_provider_is_case_insensitive(monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    set_provider("Ollama")
    assert isinstance(get_provider(), OllamaProvider)


def test_set_provider_unknown_raises():
    with pytest.raises(ValueError, match="Unknown provider"):
        set_provider("gpt5")


def test_reset_clears_override(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    set_provider("ollama")
    assert isinstance(get_provider(), OllamaProvider)
    reset_provider_cache()
    # Override gone → falls back to the env var.
    assert isinstance(get_provider(), AnthropicProvider)


# ── Ollama request/response handling ──────────────────────────────────────────

class _FakeResponse:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text

    def json(self):
        return self._payload


class _FakeClient:
    """Drop-in for httpx.Client capturing the posted body."""

    captured = {}

    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def post(self, url, json=None):
        _FakeClient.captured = {"url": url, "json": json}
        return _FakeResponse(
            payload={"message": {"content": '{"ok": true}'}, "done_reason": "stop"}
        )


def test_ollama_builds_request_and_parses(monkeypatch):
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://localhost:11434")
    monkeypatch.setenv("OLLAMA_MODEL", "llama3.2")
    monkeypatch.setattr(httpx, "Client", _FakeClient)

    provider = OllamaProvider()
    result = provider.complete(system="sys", user_text="hi", max_tokens=512, images=[b"\xff\xd8img"])

    assert isinstance(result, LLMResponse)
    assert result.text == '{"ok": true}'
    assert result.truncated is False

    body = _FakeClient.captured["json"]
    assert _FakeClient.captured["url"] == "http://localhost:11434/api/chat"
    assert body["model"] == "llama3.2"
    assert body["stream"] is False
    assert body["options"]["num_predict"] == 512
    assert body["messages"][0] == {"role": "system", "content": "sys"}
    assert body["messages"][1]["content"] == "hi"
    assert len(body["messages"][1]["images"]) == 1  # base64-encoded image present


def test_ollama_marks_truncated_on_length(monkeypatch):
    class _LenClient(_FakeClient):
        def post(self, url, json=None):
            return _FakeResponse(payload={"message": {"content": "x"}, "done_reason": "length"})

    monkeypatch.setattr(httpx, "Client", _LenClient)
    result = OllamaProvider().complete(system="s", user_text="u", max_tokens=10)
    assert result.truncated is True


def test_ollama_connect_error_maps_to_overloaded(monkeypatch):
    class _DownClient(_FakeClient):
        def post(self, url, json=None):
            raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(httpx, "Client", _DownClient)
    with pytest.raises(LLMOverloadedError):
        OllamaProvider().complete(system="s", user_text="u", max_tokens=10)


# ── Shared JSON parser ────────────────────────────────────────────────────────

def test_parse_json_plain():
    assert parse_json_response('{"a": 1}') == {"a": 1}


def test_parse_json_fenced():
    assert parse_json_response('```json\n{"a": 1}\n```') == {"a": 1}


def test_parse_json_invalid_raises():
    with pytest.raises(ValueError, match="invalid JSON"):
        parse_json_response("not json")


# ── Retry helper error mapping ────────────────────────────────────────────────

class _AuthProvider:
    name = "fake"
    model = "fake"

    async def acomplete(self, **kwargs):
        raise LLMAuthError("key missing")


async def test_retry_helper_maps_auth_to_valueerror():
    with pytest.raises(ValueError, match="key missing"):
        await acomplete_with_retry(_AuthProvider())
