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
        self.calls = 0

    async def create(self, **kwargs):
        self.calls += 1
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


def test_rate_limit_is_not_retried_as_plain_text():
    response = httpx.Response(429, request=httpx.Request("POST", "https://example.invalid"))
    error = openai.RateLimitError("quota exhausted", response=response, body={"error": "quota"})
    completions = _Completions(error=error)
    provider = _provider_with(completions)

    with pytest.raises(llm_module.LLMUnavailableError, match="rate limit exceeded"):
        asyncio.run(provider.complete_json("system", "user"))

    assert completions.calls == 1


def test_invalid_json_is_reported_instead_of_becoming_an_empty_decision():
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="not JSON"))]
    )
    provider = _provider_with(_Completions(result=response))

    with pytest.raises(llm_module.LLMUnavailableError, match="valid JSON"):
        asyncio.run(provider.complete_json("system", "user"))


def test_decision_requires_a_recommendation(monkeypatch):
    from agents import decision
    from twin import DigitalTwin

    class EmptyModel:
        async def complete_json(self, **kwargs):
            return {}

    monkeypatch.setattr(decision, "get_llm_provider", lambda: EmptyModel())
    twin = DigitalTwin(case_id="case", question="Which channel should we test?")

    with pytest.raises(ValueError, match="no recommendation"):
        asyncio.run(decision.decision_node({"twin": twin.model_dump(), "question": twin.question}))
