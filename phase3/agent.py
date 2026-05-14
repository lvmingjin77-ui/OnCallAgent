from __future__ import annotations

import json
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from phase3.llm_settings import LLMSettings, load_llm_settings

READ_FILE_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "readFile",
        "description": (
            "在 data 目录下按 basename 读取单个 UTF-8 文本文件并返回内容。"
            "不能包含路径，不能使用通配符。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "fname": {
                    "type": "string",
                    "description": "文件名，例如 sop-002.html 或 notes.txt",
                },
            },
            "required": ["fname"],
        },
    },
}


def _normalize_fname(fname: str) -> str:
    if not isinstance(fname, str):
        raise ValueError("fname 必须是字符串。")

    candidate = fname.strip()
    if not candidate:
        raise ValueError("fname 不能为空。")
    if candidate in {".", ".."}:
        raise ValueError("fname 必须是普通文件名。")
    if any(mark in candidate for mark in ("/", "\\", "*", "?", "\x00")):
        raise ValueError("fname 只能是 basename，不能包含路径或通配符。")
    return candidate


def read_file_in_data_dir(data_dir: Path, fname: str) -> str:
    normalized = _normalize_fname(fname)
    root = data_dir.resolve()
    target = (root / normalized).resolve()
    target.relative_to(root)
    if not target.is_file():
        raise FileNotFoundError(f"文件不存在: {normalized}")
    text = target.read_text(encoding="utf-8")
    max_chars = int(os.environ.get("PHASE3_MAX_FILE_CHARS", "100000"))
    if len(text) > max_chars:
        tail = max_chars // 10
        full_len = len(text)
        text = (
            text[: max_chars - tail - 80]
            + f"\n\n...[已截断，原文件 {full_len} 字符；保留开头与末尾]...\n\n"
            + text[-tail:]
        )
    return text


def write_text_in_data_dir(data_dir: Path, fname: str, content: str) -> str:
    normalized = _normalize_fname(fname)
    if not isinstance(content, str):
        raise ValueError("content 必须是字符串。")

    max_chars = int(os.environ.get("PHASE3_MAX_WRITE_CHARS", "500000"))
    if len(content) > max_chars:
        raise ValueError(f"写入内容超过上限 {max_chars} 字符。")

    root = data_dir.resolve()
    target = (root / normalized).resolve()
    target.relative_to(root)
    target.write_text(content, encoding="utf-8")
    return f"已写入 {normalized}，共 {len(content)} 字符。"


def write_bytes_in_data_dir(data_dir: Path, fname: str, raw: bytes) -> str:
    normalized = _normalize_fname(fname)
    if not isinstance(raw, bytes):
        raise ValueError("raw 必须是字节串。")

    max_bytes = int(os.environ.get("PHASE3_MAX_UPLOAD_BYTES", str(8 * 1024 * 1024)))
    if len(raw) > max_bytes:
        raise ValueError(f"文件超过上限 {max_bytes} 字节。")

    root = data_dir.resolve()
    target = (root / normalized).resolve()
    target.relative_to(root)
    target.write_bytes(raw)
    return f"已写入 {normalized}，共 {len(raw)} 字节。"

def _openai_chat(
    messages: list[dict[str, Any]],
    *,
    settings: LLMSettings,
) -> dict[str, Any]:
    url = settings.base_url.rstrip("/") + "/chat/completions"
    body = json.dumps(
        {
            "model": settings.model,
            "messages": messages,
            "tools": [READ_FILE_TOOL],
            "temperature": 0.2,
        },
        ensure_ascii=False,
    ).encode("utf-8")
    headers = {
        "Authorization": f"Bearer {settings.api_key}",
        "Content-Type": "application/json",
        "User-Agent": settings.http_user_agent,
        "Accept": "application/json",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }
    if "openrouter" in settings.base_url.lower() and settings.openrouter_http_referer:
        headers["HTTP-Referer"] = settings.openrouter_http_referer
        ref = settings.openrouter_http_referer.rstrip("/")
        if ref.startswith("http"):
            headers["Origin"] = ref
    if "openrouter" in settings.base_url.lower() and settings.openrouter_app_title:
        headers["X-Title"] = settings.openrouter_app_title

    request = Request(url, data=body, headers=headers, method="POST")
    with urlopen(request, timeout=120) as response:
        return json.loads(response.read().decode("utf-8"))


def _sse(event: str, payload: dict[str, Any]) -> bytes:
    line = json.dumps(payload, ensure_ascii=False)
    return f"event: {event}\ndata: {line}\n\n".encode("utf-8")

def _build_system_message() -> str:
    return (
        "你是内部 On-Call 值班助手。回答必须基于已用 readFile 读到的 SOP 内容；"
        "未读到的信息不要编造。你只有一个工具 readFile(fname)，它只能按 basename "
        "读取 data 目录中的单个文件，不能列目录，不能使用路径或通配符。"
        "宿主系统会为当前问题提供少量候选文件名；你只能从这些候选中选择要读的文件。"
        "若问题涉及跨团队流程、故障分级、升级路径、响应职责或需要统一多篇 SOP 口径，"
        "必须分别读取多个相关文件后再归纳。若单个文件足以覆盖问题，则不要无谓扩读。"
        "优先用中文、分步骤、简洁。\n\n"
    )


def build_system_prompt(candidate_fnames: list[str]) -> str:
    normalized_candidates: list[str] = []
    seen: set[str] = set()
    for fname in candidate_fnames:
        normalized = _normalize_fname(fname)
        if normalized in seen:
            continue
        seen.add(normalized)
        normalized_candidates.append(normalized)

    prompt = _build_system_message().rstrip()
    if normalized_candidates:
        candidate_lines = "\n".join(f"- {fname}" for fname in normalized_candidates)
        prompt += (
            "\n\n当前问题的候选文件名（由宿主系统筛选，不是目录列表）：\n"
            f"{candidate_lines}"
        )
    else:
        prompt += "\n\n当前问题未提供候选文件名。若信息不足，请明确说明无法回答。"
    return prompt


def _append_client_messages(
    messages: list[dict[str, Any]], client_messages: list[dict[str, Any]]
) -> None:
    for message in client_messages[-40:]:
        if not isinstance(message, dict):
            continue
        role = message.get("role")
        content = message.get("content")
        if role in {"user", "assistant"} and isinstance(content, str) and content.strip():
            messages.append({"role": role, "content": content})


def stream_agent(
    data_dir: Path,
    client_messages: list[dict[str, Any]],
    candidate_fnames: list[str],
) -> Iterator[bytes]:
    settings = load_llm_settings(data_dir.parent)
    if not settings.api_key:
        yield _sse(
            "error",
            {
                "message": (
                    "未配置 API Key：在项目根目录编辑 llm_config.json，填写 api_key；"
                    "也可设置环境变量 OPENROUTER_API_KEY / OPENAI_API_KEY。"
                )
            },
        )
        return

    messages: list[dict[str, Any]] = [{"role": "system", "content": build_system_prompt(candidate_fnames)}]
    _append_client_messages(messages, client_messages)

    max_rounds = int(os.environ.get("PHASE3_MAX_TOOL_ROUNDS", "8"))
    for _ in range(max_rounds):
        try:
            data = _openai_chat(messages, settings=settings)
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")[:2000]
            yield _sse("error", {"message": f"模型 HTTP 错误 {exc.code}: {body}"})
            return
        except URLError as exc:
            yield _sse("error", {"message": f"网络错误: {exc.reason}"})
            return
        except OSError as exc:
            yield _sse("error", {"message": str(exc)})
            return

        choices = data.get("choices")
        if not isinstance(choices, list) or not choices:
            yield _sse("error", {"message": "模型返回格式错误。"})
            return

        message = choices[0].get("message")
        if not isinstance(message, dict):
            yield _sse("error", {"message": "模型返回格式错误。"})
            return

        tool_calls = message.get("tool_calls")
        if isinstance(tool_calls, list) and tool_calls:
            messages.append(message)
            for call in tool_calls:
                function = call.get("function") or {}
                name = function.get("name")
                raw_arguments = function.get("arguments") or "{}"
                yield _sse("tool_call", {"name": name, "arguments": raw_arguments})

                if name != "readFile":
                    error = f"未知工具: {name}"
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": call.get("id", ""),
                            "content": error,
                        }
                    )
                    yield _sse("tool_result", {"ok": False, "error": error})
                    continue

                try:
                    arguments = (
                        json.loads(raw_arguments)
                        if isinstance(raw_arguments, str)
                        else raw_arguments
                    )
                    if not isinstance(arguments, dict):
                        raise ValueError("工具参数必须是 JSON 对象。")
                    fname = _normalize_fname(str(arguments.get("fname", "")))
                    if "content" in arguments:
                        raise ValueError("readFile 只支持 fname 参数。")
                    body = read_file_in_data_dir(data_dir, fname)
                except (OSError, ValueError, json.JSONDecodeError) as exc:
                    error = str(exc)
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": call.get("id", ""),
                            "content": f"readFile 失败: {error}",
                        }
                    )
                    yield _sse("tool_result", {"ok": False, "error": error})
                    continue

                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.get("id", ""),
                        "content": body,
                    }
                )
                yield _sse("tool_result", {"ok": True, "fname": fname, "chars": len(body)})
            continue

        content = message.get("content")
        if isinstance(content, str) and content.strip():
            messages.append({"role": "assistant", "content": content})
            yield _sse("assistant", {"text": content})
            yield _sse("done", {})
            return

        yield _sse("error", {"message": "模型没有返回回答。"})
        return

    yield _sse("error", {"message": "工具调用轮数过多，已中止。"})


def stream_error(message: str) -> Iterator[bytes]:
    yield _sse("error", {"message": message})
