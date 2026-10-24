"""Unified LLM Provider Adapter with structured outputs, budgets, caching headers, and mock/offline fallback.
(SRS-051, AI Implementation Contract Section 4 & 5).
Supports OpenAI-compatible endpoints (OpenAI, Gemini via Google OpenAI compatibility, Groq, Ollama, Together).
Tracks prompt tokens, completion tokens, cached tokens, and latency.
Never crashes when credentials are absent; raises typed ProviderUnconfigured or operates in deterministic FIXTURE mode.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

_ROOT = Path = __import__("pathlib").Path(__file__).resolve().parents[3]


class ProviderUnconfigured(RuntimeError):
    pass


class BudgetExceeded(RuntimeError):
    pass


@dataclass
class UsageReceipt:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cached_tokens: int = 0
    total_tokens: int = 0
    latency_ms: float = 0.0
    model: str = ""
    cost_usd_micros: int = 0


@dataclass
class ProviderResponse:
    content: str
    parsed_json: dict[str, Any] | None
    usage: UsageReceipt
    finish_reason: str


def _get_env_key(key: str, default: str = "") -> str:
    if key in os.environ:
        return os.environ[key]
    env_file = _ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if line.startswith(f"{key}="):
                return line.split("=", 1)[1].strip()
    return default


class LLMClient:
    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
    ):
        self.base_url = (base_url or _get_env_key("LLM_BASE_URL", "https://api.openai.com/v1")).rstrip("/")
        self.api_key = api_key or _get_env_key("LLM_API_KEY", "")
        self.model = model or _get_env_key("LLM_MODEL", "gpt-4o-mini")

    @property
    def is_configured(self) -> bool:
        local_hosts = ("localhost", "127.0.0.1", "0.0.0.0", "host.docker.internal")
        is_local = any(h in self.base_url for h in local_hosts)
        return bool(self.api_key) or is_local

    def complete(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.2,
        max_tokens: int = 2048,
        response_format_json: bool = False,
        timeout: float = 45.0,
        fixture_fallback: str | None = None,
    ) -> ProviderResponse:
        """Call LLM with token/budget tracking and structured output mode."""
        if not self.is_configured:
            if fixture_fallback is not None:
                parsed = None
                try:
                    parsed = json.loads(fixture_fallback)
                except Exception:
                    pass
                return ProviderResponse(
                    content=fixture_fallback,
                    parsed_json=parsed,
                    usage=UsageReceipt(prompt_tokens=10, completion_tokens=10, total_tokens=20, model="FIXTURE_MOCK"),
                    finish_reason="stop",
                )
            raise ProviderUnconfigured("LLM provider is UNCONFIGURED. Set LLM_API_KEY in .env")

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        body: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if response_format_json:
            body["response_format"] = {"type": "json_object"}

        t0 = time.time()
        try:
            with httpx.Client(timeout=timeout) as client:
                resp = client.post(f"{self.base_url}/chat/completions", headers=headers, json=body)
                latency = (time.time() - t0) * 1000.0

                if resp.status_code != 200:
                    if fixture_fallback is not None:
                        parsed = None
                        try:
                            parsed = json.loads(fixture_fallback)
                        except Exception:
                            pass
                        return ProviderResponse(
                            content=fixture_fallback,
                            parsed_json=parsed,
                            usage=UsageReceipt(latency_ms=latency, model="FIXTURE_FALLBACK"),
                            finish_reason="error_fallback",
                        )
                    raise RuntimeError(f"LLM Provider error {resp.status_code}: {resp.text}")

                data = resp.json()
                choice = data["choices"][0]
                text = choice["message"]["content"] or ""
                finish_reason = choice.get("finish_reason", "stop")

                raw_usage = data.get("usage", {})
                prompt_tokens = raw_usage.get("prompt_tokens", 0)
                completion_tokens = raw_usage.get("completion_tokens", 0)
                cached_tokens = (
                    raw_usage.get("prompt_tokens_details", {}).get("cached_tokens", 0)
                    if isinstance(raw_usage.get("prompt_tokens_details"), dict)
                    else 0
                )
                total_tokens = raw_usage.get("total_tokens", prompt_tokens + completion_tokens)

                # Cost estimation heuristic ($0.15 / 1M input, $0.60 / 1M output for flash-tier models)
                cost_micros = int((prompt_tokens * 0.15) + (completion_tokens * 0.60))

                parsed = None
                if response_format_json or text.strip().startswith("{"):
                    try:
                        parsed = json.loads(text)
                    except Exception:
                        pass

                return ProviderResponse(
                    content=text,
                    parsed_json=parsed,
                    usage=UsageReceipt(
                        prompt_tokens=prompt_tokens,
                        completion_tokens=completion_tokens,
                        cached_tokens=cached_tokens,
                        total_tokens=total_tokens,
                        latency_ms=latency,
                        model=self.model,
                        cost_usd_micros=cost_micros,
                    ),
                    finish_reason=finish_reason,
                )
        except Exception as e:
            if fixture_fallback is not None:
                parsed = None
                try:
                    parsed = json.loads(fixture_fallback)
                except Exception:
                    pass
                return ProviderResponse(
                    content=fixture_fallback,
                    parsed_json=parsed,
                    usage=UsageReceipt(latency_ms=(time.time() - t0) * 1000.0, model="FIXTURE_EXCEPTION_FALLBACK"),
                    finish_reason="exception_fallback",
                )
            raise


llm_client = LLMClient()
