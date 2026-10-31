"""
LLM Provider abstraction.

Supports:
  - OpenAI-compatible APIs (OpenAI, Together, Groq, Fireworks, local Ollama)
  - Structured JSON output via response_format
  - Token usage tracking

Usage:
    provider = get_llm_provider()
    result = await provider.complete(system_prompt, user_prompt)
    result = await provider.complete_json(system_prompt, user_prompt, schema)
"""
from __future__ import annotations
import json
import logging
import re
import time
from abc import ABC, abstractmethod
from typing import Any, Optional
from urllib.parse import urlsplit

import openai
from openai import AsyncOpenAI

from config import settings

logger = logging.getLogger(__name__)


class LLMUnavailableError(RuntimeError):
    """
    Raised when the LLM cannot be used at all (missing/invalid key, unreachable
    endpoint, unknown model). Agents re-raise this so the workflow fails loudly
    instead of silently producing an empty analysis.
    """


# Errors that will not be fixed by retrying with a different prompt
_FATAL_ERRORS = (
    openai.AuthenticationError,
    openai.PermissionDeniedError,
    openai.NotFoundError,
    openai.APIConnectionError,
    openai.RateLimitError,
)


def _extract_json(text: str) -> dict:
    """Pull the first JSON object out of a free-text model response."""
    text = (text or "").strip()
    # Strip markdown fences
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        return json.loads(text[start:end + 1])
    raise ValueError("No JSON object found in model response")


class LLMProvider(ABC):
    @abstractmethod
    async def complete(self, system: str, user: str, temperature: Optional[float] = None) -> str:
        ...

    @abstractmethod
    async def complete_json(
        self,
        system: str,
        user: str,
        temperature: Optional[float] = None,
    ) -> dict:
        ...


class OpenAICompatibleProvider(LLMProvider):
    def __init__(self):
        if not settings.llm_configured:
            raise LLMUnavailableError(
                "LLM_API_KEY is not set. Add it to .env (or point LLM_BASE_URL at a local "
                "OpenAI-compatible server such as Ollama)."
            )
        self.client = AsyncOpenAI(
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key or "not-needed",
            timeout=settings.llm_timeout_seconds,
            max_retries=settings.llm_max_retries,
        )
        self.model = settings.llm_model
        self.temperature = settings.llm_temperature
        self.is_gemini = (
            urlsplit(settings.llm_base_url).hostname
            == "generativelanguage.googleapis.com"
        )

    def _temp(self, temperature: Optional[float]) -> float:
        return self.temperature if temperature is None else temperature

    def _provider_options(self) -> dict[str, Any]:
        """Return request options supported by the configured provider."""
        if self.is_gemini:
            return {"reasoning_effort": settings.llm_reasoning_effort}
        return {}

    async def complete(self, system: str, user: str, temperature: Optional[float] = None) -> str:
        t0 = time.perf_counter()
        try:
            resp = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=self._temp(temperature),
                **self._provider_options(),
            )
            usage = getattr(resp, "usage", None)
            elapsed = time.perf_counter() - t0
            if usage:
                logger.info(
                    "[LLM] complete: %.2fs | in=%s out=%s total=%s | model=%s",
                    elapsed,
                    getattr(usage, "prompt_tokens", "?"),
                    getattr(usage, "completion_tokens", "?"),
                    getattr(usage, "total_tokens", "?"),
                    self.model,
                )
            else:
                logger.info("[LLM] complete: %.2fs | model=%s", elapsed, self.model)
            return resp.choices[0].message.content or ""
        except _FATAL_ERRORS as e:
            reason = "rate limit exceeded" if isinstance(e, openai.RateLimitError) else "unavailable"
            raise LLMUnavailableError(f"LLM {reason} ({type(e).__name__}): {e}") from e
        except Exception as e:
            logger.error(f"LLM complete error: {e}")
            raise

    async def complete_json(
        self,
        system: str,
        user: str,
        temperature: Optional[float] = None,
    ) -> dict:
        """
        Request structured JSON output from the model.
        Falls back to parsing the text response if the model doesn't support
        response_format=json_object.
        """
        system_with_json = (
            system + "\n\nIMPORTANT: You must respond with valid JSON only. "
            "Do not include markdown code fences, preambles, or explanations. "
            "Respond with a single JSON object."
        )
        t0 = time.perf_counter()
        try:
            resp = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_with_json},
                    {"role": "user", "content": user},
                ],
                temperature=self._temp(temperature),
                response_format={"type": "json_object"},
                **self._provider_options(),
            )
            usage = getattr(resp, "usage", None)
            elapsed = time.perf_counter() - t0
            if usage:
                logger.info(
                    "[LLM] complete_json: %.2fs | in=%s out=%s total=%s | model=%s",
                    elapsed,
                    getattr(usage, "prompt_tokens", "?"),
                    getattr(usage, "completion_tokens", "?"),
                    getattr(usage, "total_tokens", "?"),
                    self.model,
                )
            else:
                logger.info("[LLM] complete_json: %.2fs | model=%s", elapsed, self.model)
            content = resp.choices[0].message.content or "{}"
            result = _extract_json(content)
            if not isinstance(result, dict):
                raise ValueError("Model response must be a JSON object")
            return result
        except _FATAL_ERRORS as e:
            reason = "rate limit exceeded" if isinstance(e, openai.RateLimitError) else "unavailable"
            raise LLMUnavailableError(f"LLM {reason} ({type(e).__name__}): {e}") from e
        except Exception as e:
            # If response_format not supported, try plain text + parse
            logger.warning("[LLM] JSON mode failed after %.2fs (%s), falling back to text parse",
                           time.perf_counter() - t0, e)
            try:
                text = await self.complete(system_with_json, user, temperature)
                result = _extract_json(text)
                if not isinstance(result, dict):
                    raise ValueError("Model response must be a JSON object")
                return result
            except LLMUnavailableError:
                raise
            except Exception as e2:
                logger.error(f"JSON fallback also failed: {e2}")
                raise LLMUnavailableError("LLM did not return a valid JSON object") from e2


_provider: Optional[LLMProvider] = None


def get_llm_provider() -> LLMProvider:
    global _provider
    if _provider is None:
        _provider = OpenAICompatibleProvider()
    return _provider
