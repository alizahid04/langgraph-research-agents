"""
Thin async client around the OpenRouter chat-completions API.

There is no mock mode: if OPENROUTER_API_KEY is not configured, `complete()`
raises LLMNotConfiguredError immediately rather than returning synthetic text.
"""
from __future__ import annotations

import json
import logging

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from app.config import get_settings
from app.exceptions import LLMNotConfiguredError, ReportGenerationError

logger = logging.getLogger(__name__)

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


class LLMClient:
    """Wraps OpenRouter's chat completion endpoint with retries. No mock fallback."""

    def __init__(self) -> None:
        self.settings = get_settings()

    async def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        json_mode: bool = False,
    ) -> str:
        """
        Return the model's text response by calling OpenRouter.

        Raises:
            LLMNotConfiguredError: if OPENROUTER_API_KEY is not set. This is
            a configuration error, not a transient failure, so it is raised
            immediately and is never retried.
        """
        if not self.settings.openrouter_configured:
            raise LLMNotConfiguredError()
        return await self._call_openrouter(system_prompt, user_prompt, json_mode=json_mode)

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8))
    async def _call_openrouter(self, system_prompt: str, user_prompt: str, *, json_mode: bool) -> str:
        """The actual network call — only this part is retried on transient failures."""
        headers = {
            "Authorization": f"Bearer {self.settings.openrouter_api_key}",
            "Content-Type": "application/json",
        }
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        payload = {
            "model": self.settings.openrouter_model,
            "messages": messages,
            "temperature": 0.3,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        async with httpx.AsyncClient(timeout=90.0) as client:
            resp = await client.post(OPENROUTER_URL, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]

    @staticmethod
    def parse_json(text: str) -> dict:
        """
        Parse JSON strictly, stripping markdown code fences if present.

        Raises:
            ReportGenerationError: if the model's output is not valid JSON.
            There is no silent fallback to canned data — a parse failure is
            a real failure and must surface to the workflow run's error field.
        """
        cleaned = text.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.strip("`")
            if cleaned.lower().startswith("json"):
                cleaned = cleaned[4:]
        try:
            return json.loads(cleaned)
        except (json.JSONDecodeError, ValueError) as exc:
            logger.error("Failed to parse LLM JSON output: %s", text[:500])
            raise ReportGenerationError(
                f"Model returned invalid JSON and could not be parsed: {exc}"
            ) from exc
