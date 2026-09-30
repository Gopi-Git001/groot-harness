"""Harness configuration, loaded from environment variables.

.env files are read in priority order (earlier wins): the project folder's .env (CLI project mode),
~/.groot/.env (written by `groot init`), then the harness repo's .env.
"""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

from tools.paths import (HARNESS_DIR, PROJECT_DIR, PROMPTS_DIR, RESULTS_DIR,  # noqa: F401  (re-exported)
                         SPEC_PATH, WORKSPACE_DIR)

ROOT_DIR = HARNESS_DIR
USER_ENV = Path.home() / ".groot" / ".env"

for env_file in dict.fromkeys([PROJECT_DIR / ".env", USER_ENV, HARNESS_DIR / ".env"]):
    load_dotenv(env_file)


@dataclass(frozen=True)
class Config:
    endpoint: str
    model: str
    api_key: str
    temperature: float
    max_tokens: int
    merge_max_tokens: int
    timeout_seconds: float
    batch_size: int
    max_tool_steps: int


def load_config() -> Config:
    endpoint = os.getenv("GPT_OSS_ENDPOINT", "").strip()
    if not endpoint:
        raise SystemExit(
            "GPT_OSS_ENDPOINT is not set. Run `groot init`, or copy .env.example to .env and fill it in."
        )
    return Config(
        endpoint=endpoint,
        model=os.getenv("GPT_OSS_MODEL", "gpt-oss-120b"),
        # Local servers (vLLM, Ollama) accept any key; hosted providers need a real one.
        api_key=os.getenv("GPT_OSS_API_KEY") or "not-needed",
        temperature=float(os.getenv("GPT_OSS_TEMPERATURE", "0.7")),
        max_tokens=int(os.getenv("GPT_OSS_MAX_TOKENS", "8192")),
        # Merging a whole page needs far more output than a single slice.
        merge_max_tokens=int(os.getenv("HARNESS_MERGE_MAX_TOKENS", "32768")),
        timeout_seconds=float(os.getenv("GPT_OSS_TIMEOUT", "300")),
        batch_size=int(os.getenv("HARNESS_BATCH_SIZE", "10")),
        max_tool_steps=int(os.getenv("HARNESS_MAX_TOOL_STEPS", "8")),
    )
