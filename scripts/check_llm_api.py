#!/usr/bin/env python3
"""读取项目根目录 llm_config.json，对 chat/completions 发一条最小请求，检查 API 是否可用。"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from phase3.llm_settings import load_llm_settings  # noqa: E402


def main() -> int:
    s = load_llm_settings(ROOT)
    if not s.api_key:
        print("错误：未配置 api_key（llm_config.json 或环境变量）。")
        return 2

    url = s.base_url.rstrip("/") + "/chat/completions"
    body = json.dumps(
        {
            "model": s.model,
            "messages": [{"role": "user", "content": "只回复一个字：好"}],
            "max_tokens": 8,
            "temperature": 0,
        },
        ensure_ascii=False,
    ).encode("utf-8")
    headers = {
        "Authorization": f"Bearer {s.api_key}",
        "Content-Type": "application/json",
        "User-Agent": s.http_user_agent,
        "Accept": "application/json",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }
    if "openrouter" in s.base_url.lower():
        headers["HTTP-Referer"] = s.openrouter_http_referer
        headers["X-Title"] = s.openrouter_app_title
        ref = s.openrouter_http_referer.rstrip("/")
        if ref.startswith("http"):
            headers["Origin"] = ref

    print(f"POST {url}")
    print(f"model = {s.model!r}")

    try:
        req = Request(url, data=body, headers=headers, method="POST")
        with urlopen(req, timeout=60) as resp:
            raw = resp.read().decode("utf-8")
    except HTTPError as e:
        err = e.read().decode("utf-8", errors="replace")[:4000]
        print(f"HTTP {e.code}")
        print(err)
        return 1
    except URLError as e:
        print(f"网络错误: {e}")
        return 1

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        print("响应非 JSON：", raw[:500])
        return 1

    msg = (data.get("choices") or [{}])[0].get("message") or {}
    text = (msg.get("content") or "").strip()
    if text:
        print("API 可用，模型回复片段:", repr(text[:200]))
        return 0
    print("JSON 无 assistant 文本:", json.dumps(data, ensure_ascii=False)[:800])
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
