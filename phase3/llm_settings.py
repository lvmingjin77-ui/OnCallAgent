from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


@dataclass(frozen=True)
class LLMSettings:
    api_key: str
    base_url: str
    model: str
    openrouter_http_referer: str
    openrouter_app_title: str
    http_user_agent: str


def _load_file_config(repo_root: Path) -> dict[str, Any]:
    path = repo_root / "llm_config.json"
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return raw if isinstance(raw, dict) else {}


def load_llm_settings(repo_root: Path) -> LLMSettings:
    file_config = _load_file_config(repo_root)

    def pick(env_name: str, file_key: str, default: str) -> str:
        env_value = os.environ.get(env_name, "").strip()
        if env_value:
            return env_value

        file_value = str(file_config.get(file_key, "")).strip()
        if file_value:
            return file_value

        return default

    api_key = (
        os.environ.get("OPENROUTER_API_KEY", "").strip()
        or os.environ.get("OPENAI_API_KEY", "").strip()
        or str(file_config.get("api_key", "")).strip()
    )

    return LLMSettings(
        api_key=api_key,
        base_url=pick("OPENAI_BASE_URL", "base_url", "https://openrouter.fans/v1"),
        model=pick("OPENAI_MODEL", "model", "claude-opus-4-6"),
        openrouter_http_referer=pick(
            "OPENROUTER_HTTP_REFERER",
            "openrouter_http_referer",
            "http://127.0.0.1:8000",
        ),
        openrouter_app_title=pick(
            "OPENROUTER_APP_TITLE",
            "openrouter_app_title",
            "On-Call Assistant",
        ),
        http_user_agent=pick(
            "PHASE3_HTTP_USER_AGENT",
            "http_user_agent",
            _DEFAULT_USER_AGENT,
        ),
    )
