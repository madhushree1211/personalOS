import json
from collections.abc import Mapping
from typing import Any, Protocol

import httpx


class LLMClient(Protocol):
    def complete_json(self, system: str, user: str) -> dict[str, Any]:
        """Return one JSON object without logging request content."""


class LLMClientError(RuntimeError):
    """Raised when an LLM request cannot produce a JSON object."""


class LLMResponseError(LLMClientError):
    """Raised when a provider returns an unusable response."""


def _json_object(text: str) -> dict[str, Any]:
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise LLMResponseError("LLM response was not valid JSON") from exc
    if not isinstance(value, dict):
        raise LLMResponseError("LLM response was not a JSON object")
    return value


class _RESTClient:
    timeout = httpx.Timeout(10.0)
    retries = 2

    def _post(self, url: str, headers: dict[str, str], payload: dict[str, Any]) -> dict[str, Any]:
        last_error: Exception | None = None
        for _ in range(self.retries):
            try:
                response = httpx.post(
                    url,
                    headers=headers,
                    json=payload,
                    timeout=self.timeout,
                )
                response.raise_for_status()
                return response.json()
            except (httpx.HTTPError, ValueError) as exc:
                last_error = exc
        raise LLMClientError("LLM request failed") from last_error


class GeminiClient(_RESTClient):
    def __init__(self, api_key: str, model: str) -> None:
        self.api_key = api_key
        self.model = model

    def complete_json(self, system: str, user: str) -> dict[str, Any]:
        payload = {
            "system_instruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {"responseMimeType": "application/json"},
        }
        response = self._post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent",
            {"x-goog-api-key": self.api_key},
            payload,
        )
        try:
            text = response["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMResponseError("Gemini response had no text") from exc
        return _json_object(text)


class OpenAIClient(_RESTClient):
    def __init__(self, api_key: str, model: str) -> None:
        self.api_key = api_key
        self.model = model

    def complete_json(self, system: str, user: str) -> dict[str, Any]:
        payload = {
            "model": self.model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        response = self._post(
            "https://api.openai.com/v1/chat/completions",
            {"Authorization": f"Bearer {self.api_key}"},
            payload,
        )
        try:
            text = response["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMResponseError("OpenAI response had no text") from exc
        return _json_object(text)


class FakeLLMClient:
    """Deterministic test client; it performs no network calls."""

    def __init__(self, scripted_response: Mapping[str, Any] | str | Exception) -> None:
        self.scripted_response = scripted_response

    def complete_json(self, system: str, user: str) -> dict[str, Any]:
        if isinstance(self.scripted_response, Exception):
            raise self.scripted_response
        if isinstance(self.scripted_response, str):
            raise LLMResponseError("LLM response was not valid JSON")
        return dict(self.scripted_response)


def get_llm_client(settings: Any) -> LLMClient | None:
    provider = str(getattr(settings, "llm_provider", "none")).lower()
    api_key = getattr(settings, "llm_api_key", None)
    model = getattr(settings, "llm_model", "")
    if provider == "none" or not api_key:
        return None
    if provider == "gemini":
        return GeminiClient(api_key, model)
    if provider == "openai":
        return OpenAIClient(api_key, model)
    return None
