"""API client for the brain: GPT-OSS 120B behind an OpenAI-compatible endpoint."""

import time

from openai import APIStatusError, OpenAI

from config import Config

RETRIES = 3
MAX_WAIT_SECONDS = 120


class Brain:
    def __init__(self, config: Config):
        self.config = config
        self.client = OpenAI(
            base_url=config.endpoint,
            api_key=config.api_key,
            timeout=config.timeout_seconds,
        )

    def chat(self, messages: list[dict], tools: list[dict] | None = None, max_tokens: int | None = None):
        """Send one chat completion and return the reply message (may carry tool calls)."""
        extra = {"tools": tools} if tools else {}
        for attempt in range(RETRIES + 1):
            try:
                response = self.client.chat.completions.create(
                    model=self.config.model,
                    messages=messages,
                    temperature=self.config.temperature,
                    max_tokens=max_tokens or self.config.max_tokens,
                    **extra,
                )
                return response.choices[0].message
            except APIStatusError as exc:
                if attempt == RETRIES or not _retryable(exc):
                    raise
                wait = min(MAX_WAIT_SECONDS, int(exc.response.headers.get("retry-after") or 30))
                print(f"  [brain] {exc.status_code} from provider; retrying in {wait}s ({attempt + 1}/{RETRIES})")
                time.sleep(wait)

    def complete(self, system: str, user: str) -> str:
        """Send one system + user prompt and return the raw text of the reply."""
        message = self.chat(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ]
        )
        return message.content or ""


def _retryable(exc: APIStatusError) -> bool:
    """Rate limits and OpenRouter's in-flight budget limit clear on their own; other errors do not."""
    return exc.status_code == 429 or (exc.status_code == 402 and "in_flight" in str(exc))
