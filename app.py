from __future__ import annotations

import base64
import binascii
from dataclasses import asdict
from html import escape
import json
import os
from pathlib import Path
import re
from typing import Callable, Iterable
from urllib.parse import quote_plus, unquote, unquote_plus
from wsgiref.simple_server import make_server

from phase1.engine import SearchEngine, SearchHit
from phase2 import (
    DEFAULT_BGE_MODEL_REPO,
    DisabledSemanticSearchService,
    IndexNotReadyError,
    LocalBGEEmbeddingProvider,
    LocalSemanticSearchService,
    SemanticSearchService,
    SemanticSearchUnavailableError,
    resolve_default_bge_model_name,
)
from phase2.index_store import IndexStore
from phase3.agent import stream_agent, stream_error, write_bytes_in_data_dir, write_text_in_data_dir
from phase3.ui import render_v3_page


class Phase1Application:
    def __init__(
        self,
        engine: SearchEngine,
        semantic_service: SemanticSearchService,
        base_dir: Path,
    ) -> None:
        self.engine = engine
        self.semantic_service = semantic_service
        self.base_dir = base_dir
        self.data_dir = base_dir / "data"

    def __call__(
        self,
        environ: dict[str, object],
        start_response: Callable[[str, list[tuple[str, str]]], object],
    ) -> Iterable[bytes]:
        method = str(environ.get("REQUEST_METHOD", "GET")).upper()
        path = str(environ.get("PATH_INFO", ""))

        if method == "GET" and path == "/v1":
            return self._handle_search_page(environ, start_response)
        if method == "GET" and path == "/v1/search":
            return self._handle_search(environ, start_response)
        if method == "GET" and path.startswith("/v1/documents/"):
            return self._handle_document_detail(path, "/v1/documents/", self.engine, start_response)
        if method == "POST" and path == "/v1/documents":
            return self._handle_documents(environ, start_response)
        if method == "GET" and path == "/v2":
            return self._handle_semantic_search_page(environ, start_response)
        if method == "GET" and path == "/v2/search":
            return self._handle_semantic_search(environ, start_response)
        if method == "GET" and path.startswith("/v2/documents/"):
            return self._handle_document_detail(
                path, "/v2/documents/", self.semantic_service, start_response
            )
        if method == "GET" and path == "/v3":
            return self._handle_v3_page(start_response)
        if method == "POST" and path == "/v3/chat":
            return self._handle_v3_chat(environ, start_response)
        if method == "POST" and path == "/v3/upload":
            return self._handle_v3_upload(environ, start_response)
        return self._json_response(
            start_response,
            404,
            {"error": "Not found", "path": path},
        )

    def _handle_search_page(
        self,
        environ: dict[str, object],
        start_response: Callable[[str, list[tuple[str, str]]], object],
    ) -> Iterable[bytes]:
        query_string = str(environ.get("QUERY_STRING", ""))
        query = extract_query_value(query_string, "q")
        hits = self.engine.search(query) if query.strip() else []
        return self._html_response(start_response, 200, render_phase1_page(query, hits))

    def _handle_semantic_search_page(
        self,
        environ: dict[str, object],
        start_response: Callable[[str, list[tuple[str, str]]], object],
    ) -> Iterable[bytes]:
        query_string = str(environ.get("QUERY_STRING", ""))
        query = extract_query_value(query_string, "q")
        try:
            hits = self.semantic_service.search(query) if query.strip() else []
            status_message = self.semantic_service.status_message()
        except SemanticSearchUnavailableError as exc:
            hits = []
            status_message = str(exc)
        return self._html_response(
            start_response, 200, render_phase2_page(query, hits, status_message)
        )

    def _handle_search(
        self,
        environ: dict[str, object],
        start_response: Callable[[str, list[tuple[str, str]]], object],
    ) -> Iterable[bytes]:
        query_string = str(environ.get("QUERY_STRING", ""))
        query = extract_query_value(query_string, "q")
        hits = self.engine.search(query)
        payload = {
            "query": query,
            "results": [asdict(hit) for hit in hits],
        }
        return self._json_response(start_response, 200, payload)

    def _handle_semantic_search(
        self,
        environ: dict[str, object],
        start_response: Callable[[str, list[tuple[str, str]]], object],
    ) -> Iterable[bytes]:
        query_string = str(environ.get("QUERY_STRING", ""))
        query = extract_query_value(query_string, "q")
        try:
            hits = self.semantic_service.search(query)
        except SemanticSearchUnavailableError as exc:
            return self._json_response(
                start_response,
                503,
                {"error": str(exc)},
            )
        payload = {
            "query": query,
            "results": [asdict(hit) for hit in hits],
        }
        return self._json_response(start_response, 200, payload)

    def _handle_documents(
        self,
        environ: dict[str, object],
        start_response: Callable[[str, list[tuple[str, str]]], object],
    ) -> Iterable[bytes]:
        try:
            body = read_request_body(environ)
            payload = json.loads(body or "{}")
        except json.JSONDecodeError:
            return self._json_response(
                start_response,
                400,
                {"error": "Request body must be valid JSON."},
            )

        doc_id = payload.get("id")
        html = payload.get("html")
        if not isinstance(doc_id, str) or not doc_id.strip():
            return self._json_response(
                start_response,
                400,
                {"error": "Field 'id' must be a non-empty string."},
            )
        if not isinstance(html, str) or not html.strip():
            return self._json_response(
                start_response,
                400,
                {"error": "Field 'html' must be a non-empty string."},
            )

        try:
            stripped_id = doc_id.strip()
            record, _created = self.engine.upsert_document(stripped_id, html)
        except ValueError as exc:
            return self._json_response(
                start_response,
                422,
                {"error": str(exc)},
            )
        try:
            self.semantic_service.upsert_document(stripped_id, html)
        except SemanticSearchUnavailableError:
            pass

        return self._json_response(
            start_response,
            201,
            {"id": record.id, "title": record.title},
        )

    def _handle_v3_page(
        self,
        start_response: Callable[[str, list[tuple[str, str]]], object],
    ) -> Iterable[bytes]:
        html = render_v3_page(render_version_switcher("v3", ""))
        return self._html_response(start_response, 200, html)

    def _latest_v3_user_question(self, messages: list[dict[str, object]]) -> str:
        for message in reversed(messages):
            if message.get("role") != "user":
                continue
            content = message.get("content")
            if isinstance(content, str) and content.strip():
                return content.strip()
        return ""

    def _select_v3_candidate_fnames(self, messages: list[dict[str, object]]) -> list[str]:
        query = self._latest_v3_user_question(messages)
        if not query:
            return []

        limit = max(1, int(os.environ.get("PHASE3_CANDIDATE_LIMIT", "5")))
        hits = self.semantic_service.search(query)
        candidates: list[str] = []
        seen: set[str] = set()
        for hit in hits:
            fname = f"{hit.id}.html"
            if fname in seen or not (self.data_dir / fname).is_file():
                continue
            seen.add(fname)
            candidates.append(fname)
            if len(candidates) >= limit:
                break
        return candidates

    def _handle_v3_chat(
        self,
        environ: dict[str, object],
        start_response: Callable[[str, list[tuple[str, str]]], object],
    ) -> Iterable[bytes]:
        try:
            raw = read_request_body(environ)
            payload = json.loads(raw or "{}")
        except json.JSONDecodeError:
            return self._json_response(
                start_response, 400, {"error": "Invalid JSON body."}
            )

        messages = payload.get("messages")
        if not isinstance(messages, list):
            return self._json_response(
                start_response, 400, {"error": "Field 'messages' must be a list."}
            )

        cleaned: list[dict[str, object]] = []
        for item in messages[-40:]:
            if not isinstance(item, dict):
                continue
            role = item.get("role")
            content = item.get("content")
            if role in ("user", "assistant") and isinstance(content, str):
                cleaned.append({"role": role, "content": content})

        headers = [
            ("Content-Type", "text/event-stream; charset=utf-8"),
            ("Cache-Control", "no-cache"),
            ("X-Accel-Buffering", "no"),
        ]
        start_response("200 OK", headers)
        try:
            candidate_fnames = self._select_v3_candidate_fnames(cleaned)
        except SemanticSearchUnavailableError as exc:
            return stream_error(f"无法为当前问题筛选候选 SOP 文件: {exc}")

        if not candidate_fnames:
            return stream_error("未能为当前问题筛选出候选 SOP 文件，请把问题描述得更具体。")

        return stream_agent(self.data_dir, cleaned, candidate_fnames)

    def _handle_v3_upload(
        self,
        environ: dict[str, object],
        start_response: Callable[[str, list[tuple[str, str]]], object],
    ) -> Iterable[bytes]:
        try:
            raw = read_request_body(environ)
            payload = json.loads(raw or "{}")
        except json.JSONDecodeError:
            return self._json_response(
                start_response, 400, {"error": "Invalid JSON body."}
            )

        fname_raw = payload.get("fname")
        if not isinstance(fname_raw, str) or not fname_raw.strip():
            return self._json_response(
                start_response, 400, {"error": "Field 'fname' must be a non-empty string."}
            )
        fname = os.path.basename(fname_raw.strip())
        if fname != fname_raw.strip() or not fname:
            return self._json_response(
                start_response, 400, {"error": "Field 'fname' must be a plain basename."}
            )

        b64 = payload.get("content_base64")
        if isinstance(b64, str) and b64.strip():
            try:
                raw_bytes = base64.b64decode(b64, validate=True)
            except binascii.Error:
                return self._json_response(
                    start_response, 400, {"error": "Invalid content_base64."}
                )
            try:
                message = write_bytes_in_data_dir(self.data_dir, fname, raw_bytes)
            except (ValueError, OSError) as exc:
                return self._json_response(
                    start_response, 400, {"error": str(exc)}
                )
            return self._json_response(
                start_response,
                201,
                {
                    "ok": True,
                    "fname": fname,
                    "bytes": len(raw_bytes),
                    "message": message,
                },
            )

        content = payload.get("content")
        if isinstance(content, str):
            try:
                message = write_text_in_data_dir(self.data_dir, fname, content)
            except (ValueError, OSError) as exc:
                return self._json_response(
                    start_response, 400, {"error": str(exc)}
                )
            return self._json_response(
                start_response,
                201,
                {
                    "ok": True,
                    "fname": fname,
                    "chars": len(content),
                    "message": message,
                },
            )

        return self._json_response(
            start_response,
            400,
            {"error": "Provide 'content' (UTF-8 text) or 'content_base64' (binary)."},
        )

    def _handle_document_detail(
        self,
        path: str,
        route_prefix: str,
        engine: SearchEngine | SemanticSearchService,
        start_response: Callable[[str, list[tuple[str, str]]], object],
    ) -> Iterable[bytes]:
        doc_id = unquote(path.removeprefix(route_prefix)).strip()
        if not doc_id:
            return self._json_response(
                start_response,
                404,
                {"error": "Not found", "path": path},
            )

        document = engine.get_document(doc_id)
        if document is None:
            return self._json_response(
                start_response,
                404,
                {"error": "Document not found.", "id": doc_id},
            )

        return self._html_response(
            start_response,
            200,
            document.raw_html,
            extra_headers=[
                (
                    "Content-Security-Policy",
                    "default-src 'self'; script-src 'none'; style-src 'unsafe-inline' 'self'; img-src 'self' data:;",
                )
            ],
        )

    def _json_response(
        self,
        start_response: Callable[[str, list[tuple[str, str]]], object],
        status_code: int,
        payload: dict[str, object],
    ) -> Iterable[bytes]:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        start_response(
            f"{status_code} {reason_phrase(status_code)}",
            [
                ("Content-Type", "application/json; charset=utf-8"),
                ("Content-Length", str(len(body))),
            ],
        )
        return [body]

    def _html_response(
        self,
        start_response: Callable[[str, list[tuple[str, str]]], object],
        status_code: int,
        html: str,
        extra_headers: list[tuple[str, str]] | None = None,
    ) -> Iterable[bytes]:
        body = html.encode("utf-8")
        headers = [
            ("Content-Type", "text/html; charset=utf-8"),
            ("Content-Length", str(len(body))),
        ]
        if extra_headers:
            headers.extend(extra_headers)
        start_response(
            f"{status_code} {reason_phrase(status_code)}",
            headers,
        )
        return [body]


def read_request_body(environ: dict[str, object]) -> str:
    try:
        content_length = int(str(environ.get("CONTENT_LENGTH", "0")) or "0")
    except ValueError:
        content_length = 0

    stream = environ.get("wsgi.input")
    if stream is None:
        return ""

    body = stream.read(content_length)
    return body.decode("utf-8")


def extract_query_value(query_string: str, field_name: str) -> str:
    # Accept a relaxed query form where reserved '&' characters may appear
    # inside the value unescaped until the next explicit key=value segment.
    parts = query_string.split("&")
    index = 0
    while index < len(parts):
        segment = parts[index]
        if "=" not in segment:
            index += 1
            continue

        key, value = segment.split("=", 1)
        if unquote_plus(key) != field_name:
            index += 1
            continue

        value_parts = [value]
        lookahead = index + 1
        while lookahead < len(parts):
            next_segment = parts[lookahead]
            if "=" in next_segment:
                break
            value_parts.append(next_segment)
            lookahead += 1

        return unquote_plus("&".join(value_parts))

    return ""


def reason_phrase(status_code: int) -> str:
    phrases = {
        200: "OK",
        201: "Created",
        400: "Bad Request",
        404: "Not Found",
        503: "Service Unavailable",
        422: "Unprocessable Entity",
    }
    return phrases.get(status_code, "OK")


def render_phase1_page(query: str = "", results: list[SearchHit] | None = None) -> str:
    return render_search_page(
        query=query,
        results=results,
        active_version="v1",
        page_title="Phase 1 搜索引擎",
        hero_title="On-Call 搜索引擎",
        description="Phase 1 只做一件事：对清洗后的 SOP 正文做稳定的关键词检索。",
        form_action="/v1",
        placeholder="输入关键词，例如 OOM、CDN、故障、&",
        document_href_prefix="/v1/documents/",
        empty_prompt="输入关键词后开始搜索。",
    )


def render_phase2_page(
    query: str = "",
    results: list[SearchHit] | None = None,
    status_message: str | None = None,
) -> str:
    return render_search_page(
        query=query,
        results=results,
        active_version="v2",
        page_title="Phase 2 语义搜索",
        hero_title="On-Call 语义搜索",
        description="Phase 2 会把问题映射到 SOP 的语义主题，而不是只看字面命中。",
        form_action="/v2",
        placeholder="输入问题，例如 服务器挂了、黑客攻击、机器学习模型出问题",
        document_href_prefix="/v2/documents/",
        empty_prompt="输入自然语言问题后开始搜索。",
        status_message=status_message,
    )


def render_search_page(
    *,
    query: str,
    results: list[SearchHit] | None,
    active_version: str,
    page_title: str,
    hero_title: str,
    description: str,
    form_action: str,
    placeholder: str,
    document_href_prefix: str,
    empty_prompt: str,
    status_message: str | None = None,
) -> str:
    safe_query = escape(query, quote=True)
    rendered_results = render_search_results(results or [], query, document_href_prefix)
    switcher = render_version_switcher(active_version, query)
    empty_message = (
        status_message
        if status_message
        else (
            empty_prompt
            if not query.strip()
            else ("没有命中结果。" if not (results or []) else "")
        )
    )
    safe_empty_message = escape(empty_message)

    template = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>__PAGE_TITLE__</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f5efe6;
      --panel: #fffaf2;
      --ink: #1f2933;
      --muted: #52606d;
      --line: #d9cbb6;
      --accent: #9b3d12;
      --accent-soft: #f2d3bf;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: "Iowan Old Style", "Songti SC", serif;
      background:
        radial-gradient(circle at top left, rgba(155, 61, 18, 0.10), transparent 24rem),
        linear-gradient(180deg, #f8f1e8 0%, #f3eadf 100%);
      color: var(--ink);
      min-height: 100vh;
    }
    main {
      max-width: 56rem;
      margin: 0 auto;
      padding: 3rem 1.25rem 4rem;
    }
    .panel {
      background: rgba(255, 250, 242, 0.92);
      border: 1px solid var(--line);
      border-radius: 1.25rem;
      box-shadow: 0 24px 60px rgba(54, 37, 19, 0.10);
      overflow: hidden;
    }
    .switcher {
      display: flex;
      gap: 0.75rem;
      padding: 1.25rem 2rem 0;
    }
    .mode-link {
      display: inline-flex;
      align-items: center;
      gap: 0.45rem;
      padding: 0.6rem 0.9rem;
      border: 1px solid var(--line);
      border-radius: 999px;
      background: rgba(255, 250, 242, 0.7);
      color: var(--muted);
      text-decoration: none;
      transition: border-color 140ms ease, background 140ms ease, color 140ms ease;
    }
    .mode-link:hover,
    .mode-link:focus-visible {
      border-color: #b9835a;
      color: var(--ink);
      outline: none;
    }
    .mode-link.is-active {
      border-color: var(--accent);
      background: var(--accent);
      color: white;
    }
    .mode-label {
      font-weight: 700;
    }
    .mode-note {
      font-size: 0.92rem;
    }
    .hero {
      padding: 2rem 2rem 1.25rem;
      border-bottom: 1px solid var(--line);
      background:
        linear-gradient(135deg, rgba(155, 61, 18, 0.08), rgba(255, 250, 242, 0));
    }
    h1 {
      margin: 0 0 0.5rem;
      font-size: clamp(2rem, 4vw, 3rem);
      line-height: 1.05;
    }
    p {
      margin: 0;
      color: var(--muted);
      line-height: 1.6;
    }
    form {
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 0.75rem;
      padding: 1.25rem 2rem;
      border-bottom: 1px solid var(--line);
    }
    input, button {
      font: inherit;
    }
    input {
      width: 100%;
      padding: 0.95rem 1rem;
      border-radius: 0.9rem;
      border: 1px solid var(--line);
      background: white;
      color: var(--ink);
    }
    button {
      padding: 0.95rem 1.2rem;
      border: 0;
      border-radius: 0.9rem;
      background: var(--accent);
      color: white;
      cursor: pointer;
    }
    .results {
      display: grid;
      gap: 1rem;
      padding: 1.25rem 2rem 2rem;
    }
    .result {
      display: block;
      padding: 1rem 1rem 0.9rem;
      border: 1px solid var(--line);
      border-radius: 1rem;
      background: var(--panel);
      color: inherit;
      text-decoration: none;
      transition: transform 140ms ease, box-shadow 140ms ease, border-color 140ms ease;
    }
    .result:hover,
    .result:focus-visible {
      transform: translateY(-1px);
      box-shadow: 0 14px 28px rgba(54, 37, 19, 0.10);
      border-color: #b9835a;
      outline: none;
    }
    .result h2 {
      margin: 0 0 0.4rem;
      font-size: 1.1rem;
    }
    .hit {
      font-weight: 700;
      color: #7a2600;
      background: rgba(242, 211, 191, 0.72);
      padding: 0 0.12em;
      border-radius: 0.22em;
    }
    .meta {
      display: flex;
      justify-content: space-between;
      gap: 1rem;
      margin-bottom: 0.45rem;
      color: var(--muted);
      font-size: 0.95rem;
    }
    .empty {
      padding: 1.5rem 2rem 2rem;
      color: var(--muted);
    }
    .pill {
      display: inline-block;
      padding: 0.18rem 0.55rem;
      border-radius: 999px;
      background: var(--accent-soft);
      color: var(--accent);
    }
    .result-note {
      margin-top: 0.75rem;
      color: var(--accent);
      font-size: 0.92rem;
    }
    @media (max-width: 640px) {
      form {
        grid-template-columns: 1fr;
      }
      .meta {
        flex-direction: column;
        gap: 0.2rem;
      }
    }
  </style>
</head>
<body>
  <main>
    <section class="panel">
      <nav class="switcher" aria-label="Search mode">
        __VERSION_SWITCHER__
      </nav>
      <div class="hero">
        <h1>__HERO_TITLE__</h1>
        <p>__DESCRIPTION__</p>
      </div>
      <form id="search-form" action="__FORM_ACTION__" method="get">
        <input id="query" name="q" type="text" placeholder="__PLACEHOLDER__" autocomplete="off" value="__SAFE_QUERY__">
        <button type="submit">搜索</button>
      </form>
      <div id="results" class="results">__RENDERED_RESULTS__</div>
      <div id="empty" class="empty">__EMPTY_MESSAGE__</div>
    </section>
  </main>
  <script>
    (function() {
      const ACTIVE_VERSION = "__ACTIVE_VERSION__";
      const STATE_KEY = "oncall.pageState." + ACTIVE_VERSION;
      const URLS_KEY = "oncall.pageUrls";
      const RESTORE_KEY = "oncall.restoreTarget";
      const queryInput = document.getElementById("query");
      const results = document.getElementById("results");
      const empty = document.getElementById("empty");
      const form = document.getElementById("search-form");

      function readJson(key, fallback) {
        try {
          const raw = sessionStorage.getItem(key);
          return raw ? JSON.parse(raw) : fallback;
        } catch (_error) {
          return fallback;
        }
      }

      function writeUrls(url) {
        const urls = readJson(URLS_KEY, {});
        urls[ACTIVE_VERSION] = url;
        sessionStorage.setItem(URLS_KEY, JSON.stringify(urls));
      }

      function saveState() {
        const state = {
          url: window.location.pathname + window.location.search,
          query: queryInput ? queryInput.value : "",
          resultsHtml: results ? results.innerHTML : "",
          emptyText: empty ? empty.textContent : "",
          scrollY: window.scrollY || 0
        };
        sessionStorage.setItem(STATE_KEY, JSON.stringify(state));
        writeUrls(state.url);
      }

      function restoreStateIfNeeded() {
        const target = sessionStorage.getItem(RESTORE_KEY);
        if (target !== ACTIVE_VERSION) {
          return;
        }
        sessionStorage.removeItem(RESTORE_KEY);
        const state = readJson(STATE_KEY, null);
        if (!state) {
          return;
        }
        if (queryInput && typeof state.query === "string") {
          queryInput.value = state.query;
        }
        if (results && typeof state.resultsHtml === "string") {
          results.innerHTML = state.resultsHtml;
        }
        if (empty && typeof state.emptyText === "string") {
          empty.textContent = state.emptyText;
        }
        if (typeof state.url === "string" && state.url) {
          history.replaceState(null, "", state.url);
        }
        requestAnimationFrame(function() {
          window.scrollTo(0, Number(state.scrollY) || 0);
        });
      }

      function syncSwitcherLinks() {
        const urls = readJson(URLS_KEY, {});
        document.querySelectorAll(".mode-link[data-version]").forEach(function(link) {
          const version = link.getAttribute("data-version");
          if (!version) {
            return;
          }
          const savedUrl = urls[version];
          if (savedUrl) {
            link.href = savedUrl;
          }
          link.addEventListener("click", function() {
            try {
              sessionStorage.setItem(RESTORE_KEY, version);
            } catch (_error) {}
          });
        });
      }

      syncSwitcherLinks();
      restoreStateIfNeeded();
      saveState();

      if (queryInput) {
        queryInput.addEventListener("input", saveState);
        queryInput.addEventListener("keydown", function(event) {
          if (event.key !== "Enter") {
            return;
          }
          event.preventDefault();
          saveState();
          if (form && typeof form.requestSubmit === "function") {
            form.requestSubmit();
            return;
          }
          if (form) {
            form.submit();
          }
        });
      }
      if (form) {
        form.addEventListener("submit", saveState);
      }
      window.addEventListener("pagehide", saveState);
      window.addEventListener("beforeunload", saveState);
    })();
  </script>
</body>
</html>
"""
    return (
        template.replace("__PAGE_TITLE__", escape(page_title))
        .replace("__HERO_TITLE__", escape(hero_title))
        .replace("__DESCRIPTION__", escape(description))
        .replace("__FORM_ACTION__", escape(form_action, quote=True))
        .replace("__PLACEHOLDER__", escape(placeholder, quote=True))
        .replace("__SAFE_QUERY__", safe_query)
        .replace("__VERSION_SWITCHER__", switcher)
        .replace("__RENDERED_RESULTS__", rendered_results)
        .replace("__EMPTY_MESSAGE__", safe_empty_message)
        .replace("__ACTIVE_VERSION__", active_version)
    )


def render_version_switcher(active_version: str, query: str) -> str:
    items = (
        ("v1", "/v1", "Phase 1", "关键词检索"),
        ("v2", "/v2", "Phase 2", "语义搜索"),
        ("v3", "/v3", "Phase 3", "On-Call 助手"),
    )
    rendered: list[str] = []
    for version, path, label, note in items:
        active_class = " is-active" if version == active_version else ""
        rendered.append(
            f'<a class="mode-link{active_class}" data-version="{escape(version, quote=True)}" href="{escape(path, quote=True)}">'
            f'<span class="mode-label">{escape(label)}</span>'
            f'<span class="mode-note">{escape(note)}</span>'
            "</a>"
        )
    return "".join(rendered)


def render_search_results(
    results: list[SearchHit], query: str, document_href_prefix: str
) -> str:
    if not results:
        return ""

    cards = []
    for result in results:
        cards.append(
            f"""
        <a class="result" href="{escape(document_href_prefix, quote=True)}{escape(result.id, quote=True)}">
          <div class="meta">
            <span class="pill">{escape(result.id)}</span>
            <span>score {result.score:.4f}</span>
          </div>
          <h2>{highlight_matches_html(result.title, query)}</h2>
          <p>{highlight_matches_html(result.snippet, query)}</p>
          <p class="result-note">打开原始 SOP 页面</p>
        </a>"""
        )
    return "".join(cards)


def highlight_matches_html(text: str, query: str) -> str:
    terms = query_terms(query)
    if not terms:
        return escape(text)

    pattern = re.compile("|".join(re.escape(term) for term in terms), re.IGNORECASE)
    pieces: list[str] = []
    last_index = 0

    for match in pattern.finditer(text):
        pieces.append(escape(text[last_index : match.start()]))
        pieces.append(f'<strong class="hit">{escape(match.group(0))}</strong>')
        last_index = match.end()

    pieces.append(escape(text[last_index:]))
    return "".join(pieces)


def query_terms(query: str) -> list[str]:
    unique_terms = {term for term in query.strip().split() if term}
    return sorted(unique_terms, key=lambda term: (-len(term), term.casefold()))


def create_app(
    base_dir: Path | None = None,
    semantic_service: SemanticSearchService | None = None,
) -> Phase1Application:
    root = base_dir or Path(__file__).resolve().parent
    engine = SearchEngine()
    data_dir = root / "data"
    engine.load_directory(data_dir)
    resolved_semantic_service = semantic_service or build_default_semantic_service(root)
    return Phase1Application(engine, resolved_semantic_service, root)


def build_default_semantic_service(root: Path) -> SemanticSearchService:
    index_dir = Path(os.environ.get("PHASE2_INDEX_DIR", str(root / ".phase2_index")))
    if not IndexStore(index_dir).exists():
        return DisabledSemanticSearchService(
            "Phase 2 index not built. Run `python3 -m phase2.rebuild_index` after "
            "installing local embedding dependencies."
        )

    resolved_model_name = os.environ.get(
        "PHASE2_MODEL_NAME",
        resolve_default_bge_model_name(root),
    )
    local_files_only_default = (
        "1"
        if resolved_model_name != DEFAULT_BGE_MODEL_REPO and Path(resolved_model_name).exists()
        else "0"
    )
    provider = LocalBGEEmbeddingProvider(
        model_name=resolved_model_name,
        device=os.environ.get("PHASE2_DEVICE", "cpu"),
        batch_size=int(os.environ.get("PHASE2_BATCH_SIZE", "32")),
        local_files_only=os.environ.get(
            "PHASE2_LOCAL_FILES_ONLY", local_files_only_default
        )
        == "1",
    )
    try:
        return LocalSemanticSearchService(
            index_dir=index_dir,
            provider=provider,
        )
    except (FileNotFoundError, ValueError, IndexNotReadyError) as exc:
        return DisabledSemanticSearchService(str(exc))


def main() -> None:
    base_dir = Path(__file__).resolve().parent
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "8000"))
    app = create_app(base_dir)

    with make_server(host, port, app) as server:
        print(f"Serving Phase 1 on http://{host}:{port}/v1")
        print(f"Serving Phase 2 on http://{host}:{port}/v2")
        print(f"Serving Phase 3 on http://{host}:{port}/v3 (upload POST /v3/upload)")
        server.serve_forever()


if __name__ == "__main__":
    main()
