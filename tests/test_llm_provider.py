"""Regression checks for LLM timeout and Gemini request configuration."""
import asyncio
from types import SimpleNamespace

import httpx
import openai
import pytest

from providers import llm as llm_module


class _Completions:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.kwargs = None

    async def create(self, **kwargs):
        self.kwargs = kwargs
        if self.error:
            raise self.error
        return self.result


def _provider_with(completions):
    provider = llm_module.OpenAICompatibleProvider.__new__(
        llm_module.OpenAICompatibleProvider
    )
    provider.model = "gemini-3.8-flash"
    provider.temperature = 0.3
    provider.is_gemini = True
    provider.client = SimpleNamespace(
        chat=SimpleNamespace(completions=completions)
    )
    return provider


def test_provider_uses_configured_timeout_and_retry_budget(monkeypatch):
    captured = {}

    class FakeAsyncOpenAI:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(llm_module, "AsyncOpenAI", FakeAsyncOpenAI)
    monkeypatch.setattr(llm_module.settings, "llm_api_key", "test-key")
    monkeypatch.setattr(llm_module.settings, "llm_timeout_seconds", 45.0)
    monkeypatch.setattr(llm_module.settings, "llm_max_retries", 1)

    llm_module.OpenAICompatibleProvider()

    assert captured["timeout"] == 45.0
    assert captured["max_retries"] == 1


def test_gemini_json_request_uses_low_reasoning_effort():
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content='{"ok": true}'))]
    )
    completions = _Completions(result=response)
    provider = _provider_with(completions)

    assert asyncio.run(provider.complete_json("system", "user")) == {"ok": True}
    assert completions.kwargs["reasoning_effort"] == "low"


def test_timeout_is_reported_as_llm_unavailable():
    timeout = openai.APITimeoutError(
        request=httpx.Request("POST", "https://example.invalid")
    )
    provider = _provider_with(_Completions(error=timeout))

    with pytest.raises(llm_module.LLMUnavailableError, match="Request timed out"):
        asyncio.run(provider.complete_json("system", "user"))
