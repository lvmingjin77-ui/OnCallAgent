from __future__ import annotations

from io import BytesIO
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from wsgiref.util import setup_testing_defaults

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import create_app  # noqa: E402
from phase1.engine import SearchHit  # noqa: E402
from phase3.agent import (  # noqa: E402
    READ_FILE_TOOL,
    _build_system_message,
    build_system_prompt,
    read_file_in_data_dir,
    stream_agent,
)
from phase3.llm_settings import LLMSettings, load_llm_settings  # noqa: E402


class FakePhase3SemanticService:
    def is_available(self) -> bool:
        return True

    def status_message(self) -> str | None:
        return None

    def search(self, query: str) -> list[SearchHit]:
        lowered = query.casefold()
        if "主从" in lowered or "数据库" in lowered:
            ids = ["sop-002"]
        elif "oom" in lowered:
            ids = ["sop-001"]
        elif "p0" in lowered or "故障" in lowered:
            ids = ["sop-001", "sop-004", "sop-005"]
        elif "入侵" in lowered or "攻击" in lowered:
            ids = ["sop-005"]
        elif "推荐" in lowered or "模型" in lowered:
            ids = ["sop-008"]
        else:
            ids = ["sop-001"]
        return [
            SearchHit(id=doc_id, title=doc_id, snippet="", score=1.0 - index * 0.1)
            for index, doc_id in enumerate(ids)
        ]

    def get_document(self, doc_id: str):
        return None

    def upsert_document(self, doc_id: str, html: str) -> None:
        return None


class Phase3Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.app = create_app(ROOT, semantic_service=FakePhase3SemanticService())

    def test_read_file_tool_schema_is_read_only(self) -> None:
        function = READ_FILE_TOOL["function"]
        self.assertEqual(function["name"], "readFile")
        properties = function["parameters"]["properties"]
        self.assertEqual(set(properties), {"fname"})
        self.assertEqual(function["parameters"]["required"], ["fname"])

    def test_system_message_matches_expected_prompt(self) -> None:
        prompt = _build_system_message()
        self.assertIn("回答必须基于已用 readFile 读到的 SOP 内容", prompt)
        self.assertIn("未读到的信息不要编造", prompt)
        self.assertIn("宿主系统会为当前问题提供少量候选文件名", prompt)
        self.assertIn("必须分别读取多个相关文件后再归纳", prompt)
        self.assertIn("无谓扩读", prompt)
        self.assertNotIn("传入 content", prompt)

    def test_system_prompt_includes_host_candidates_only(self) -> None:
        text = build_system_prompt(["sop-001.html", "sop-004.html"])
        self.assertIn("sop-001.html", text)
        self.assertIn("sop-004.html", text)
        self.assertIn("候选文件名", text)
        self.assertNotIn("可用 SOP 文件", text)

    def test_read_file_rejects_path_traversal(self) -> None:
        with self.assertRaises(ValueError):
            read_file_in_data_dir(ROOT / "data", "../README.md")
        with self.assertRaises(ValueError):
            read_file_in_data_dir(ROOT / "data", "a/b.html")
        with self.assertRaises(ValueError):
            read_file_in_data_dir(ROOT / "data", "*.html")

    def test_read_file_reads_sop(self) -> None:
        body = read_file_in_data_dir(ROOT / "data", "sop-001.html")
        self.assertIn("OOM", body)

    def test_v3_page_ok(self) -> None:
        status, headers, raw = self._request("GET", "/v3", "")
        self.assertEqual(status, 200)
        self.assertIn("text/html", headers.get("Content-Type", ""))
        html = raw.decode("utf-8")
        self.assertIn("readFile(fname)", html)
        self.assertIn("/v3/upload", html)
        self.assertIn('data-version="v3"', html)
        self.assertIn("const ACTIVE_VERSION = 'v3'", html)
        self.assertIn("oncall.pageState.", html)

    def test_load_llm_settings_reads_llm_config_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "llm_config.json").write_text(
                '{"api_key":"secret-from-file","base_url":"https://example.com/v1",'
                '"model":"anthropic/claude-3-haiku","openrouter_http_referer":"https://a",'
                '"openrouter_app_title":"T"}',
                encoding="utf-8",
            )
            settings = load_llm_settings(root)
            self.assertEqual(settings.api_key, "secret-from-file")
            self.assertEqual(settings.base_url, "https://example.com/v1")
            self.assertEqual(settings.model, "anthropic/claude-3-haiku")
            self.assertEqual(settings.openrouter_http_referer, "https://a")
            self.assertEqual(settings.openrouter_app_title, "T")
            self.assertIn("Chrome", settings.http_user_agent)

    def test_v3_upload_json_writes_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data = root / "data"
            data.mkdir()
            (data / "sop-001.html").write_text(
                "<html><head><title>T</title></head><body>x</body></html>",
                encoding="utf-8",
            )
            app = create_app(root)
            status, _, _raw = self._request(
                "POST",
                "/v3/upload",
                "",
                body={"fname": "uploaded-v3.txt", "content": "ok"},
                app=app,
            )
            self.assertEqual(status, 201)
            self.assertEqual((data / "uploaded-v3.txt").read_text(encoding="utf-8"), "ok")

    def test_stream_agent_reads_target_sop_from_host_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data_dir = root / "data"
            data_dir.mkdir()
            (data_dir / "sop-002.html").write_text(
                (
                    "<html><head><title>数据库 DBA On-Call SOP</title></head><body>"
                    "<h1>数据库 DBA On-Call SOP</h1>"
                    "<h2>主从延迟超过30秒</h2>"
                    "<p>先检查复制线程状态，再排查慢查询和大事务。</p>"
                    "</body></html>"
                ),
                encoding="utf-8",
            )

            captured_messages: list[list[dict[str, object]]] = []

            def fake_openai_chat(messages, *, settings):
                snapshot = json.loads(json.dumps(messages, ensure_ascii=False))
                captured_messages.append(snapshot)
                if len(captured_messages) == 1:
                    self.assertIn("回答必须基于已用 readFile 读到的 SOP 内容", snapshot[0]["content"])
                    self.assertIn("sop-002.html", snapshot[0]["content"])
                    self.assertNotIn("sop-003.html", snapshot[0]["content"])
                    return {
                        "choices": [
                            {
                                "message": {
                                    "tool_calls": [
                                        {
                                            "id": "call-1",
                                            "function": {
                                                "name": "readFile",
                                                "arguments": json.dumps(
                                                    {"fname": "sop-002.html"},
                                                    ensure_ascii=False,
                                                ),
                                            },
                                        }
                                    ]
                                }
                            }
                        ]
                    }
                tool_contents = [m["content"] for m in snapshot if m.get("role") == "tool"]
                self.assertIn("主从延迟超过30秒", tool_contents[-1])
                return {
                    "choices": [
                        {
                            "message": {
                                "content": (
                                    "先检查复制线程状态，再排查慢查询和大事务。\n\n"
                                    "已读取文件：sop-002.html"
                                )
                            }
                        }
                    ]
                }

            fake_settings = LLMSettings(
                api_key="test-key",
                base_url="https://example.com/v1",
                model="test-model",
                openrouter_http_referer="",
                openrouter_app_title="",
                http_user_agent="Mozilla/5.0 test",
            )

            with patch("phase3.agent.load_llm_settings", return_value=fake_settings):
                with patch("phase3.agent._openai_chat", side_effect=fake_openai_chat):
                    raw = b"".join(
                        stream_agent(
                            data_dir,
                            [
                                {
                                    "role": "user",
                                    "content": "数据库主从延迟超过30秒怎么处理？",
                                }
                            ],
                            ["sop-002.html"],
                        )
                    )

            events = self._parse_sse(raw)
            event_names = [name for name, _ in events]
            self.assertEqual(
                event_names,
                ["tool_call", "tool_result", "assistant", "done"],
            )
            self.assertEqual(events[0][1]["name"], "readFile")
            self.assertIn("sop-002.html", events[0][1]["arguments"])
            self.assertFalse((data_dir / "sop_manifest.json").exists())

    def test_stream_agent_reads_multiple_files_for_cross_team_question(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data_dir = root / "data"
            data_dir.mkdir()
            (data_dir / "sop-001.html").write_text(
                (
                    "<html><head><title>后端服务 On-Call SOP</title></head><body>"
                    "<h1>后端服务 On-Call SOP</h1>"
                    "<h2>P0 故障</h2>"
                    "<p>确认故障级别并通知值班负责人。</p>"
                    "</body></html>"
                ),
                encoding="utf-8",
            )
            (data_dir / "sop-004.html").write_text(
                (
                    "<html><head><title>SRE 基础设施 On-Call SOP</title></head><body>"
                    "<h1>SRE 基础设施 On-Call SOP</h1>"
                    "<h2>P0 故障</h2>"
                    "<p>启动跨团队升级流程并建立故障群。</p>"
                    "</body></html>"
                ),
                encoding="utf-8",
            )

            def fake_openai_chat(messages, *, settings):
                snapshot = json.loads(json.dumps(messages, ensure_ascii=False))
                tool_contents = [m["content"] for m in snapshot if m.get("role") == "tool"]
                if not tool_contents:
                    return {
                        "choices": [
                            {
                                "message": {
                                    "tool_calls": [
                                        {
                                            "id": "call-1",
                                            "function": {
                                                "name": "readFile",
                                                "arguments": json.dumps(
                                                    {"fname": "sop-001.html"},
                                                    ensure_ascii=False,
                                                ),
                                            },
                                        },
                                        {
                                            "id": "call-2",
                                            "function": {
                                                "name": "readFile",
                                                "arguments": json.dumps(
                                                    {"fname": "sop-004.html"},
                                                    ensure_ascii=False,
                                                ),
                                            },
                                        },
                                    ]
                                }
                            }
                        ]
                    }
                self.assertEqual(len(tool_contents), 2)
                self.assertIn("确认故障级别", tool_contents[0])
                self.assertIn("启动跨团队升级流程", tool_contents[1])
                return {
                    "choices": [
                        {
                            "message": {
                                "content": (
                                    "先确认故障级别并通知值班负责人，再启动跨团队升级流程并建立故障群。"
                                )
                            }
                        }
                    ]
                }

            fake_settings = LLMSettings(
                api_key="test-key",
                base_url="https://example.com/v1",
                model="test-model",
                openrouter_http_referer="",
                openrouter_app_title="",
                http_user_agent="Mozilla/5.0 test",
            )

            with patch("phase3.agent.load_llm_settings", return_value=fake_settings):
                with patch("phase3.agent._openai_chat", side_effect=fake_openai_chat):
                    raw = b"".join(
                        stream_agent(
                            data_dir,
                            [{"role": "user", "content": "P0 故障的响应流程是什么？"}],
                            ["sop-001.html", "sop-004.html"],
                        )
                    )

            event_names = [name for name, _ in self._parse_sse(raw)]
            self.assertEqual(
                event_names,
                ["tool_call", "tool_result", "tool_call", "tool_result", "assistant", "done"],
            )

    def test_v3_chat_uses_host_selected_candidates(self) -> None:
        def fake_stream_agent(data_dir, client_messages, candidate_fnames):
            self.assertEqual(candidate_fnames, ["sop-005.html"])
            self.assertEqual(client_messages[-1]["content"], "怀疑有人入侵了系统")
            yield b"event: done\ndata: {}\n\n"

        with patch("app.stream_agent", side_effect=fake_stream_agent):
            status, headers, raw = self._request(
                "POST",
                "/v3/chat",
                "",
                body={"messages": [{"role": "user", "content": "怀疑有人入侵了系统"}]},
            )
        self.assertEqual(status, 200)
        self.assertIn("event-stream", headers.get("Content-Type", ""))
        self.assertIn(b"event: done", raw)

    def test_v3_chat_without_key_returns_sse_error(self) -> None:
        missing_key_settings = LLMSettings(
            api_key="",
            base_url="https://example.com/v1",
            model="test-model",
            openrouter_http_referer="",
            openrouter_app_title="",
            http_user_agent="Mozilla/5.0 test",
        )
        with patch("phase3.agent.load_llm_settings", return_value=missing_key_settings):
            status, headers, raw = self._request(
                "POST",
                "/v3/chat",
                "",
                body={"messages": [{"role": "user", "content": "hi"}]},
            )
        self.assertEqual(status, 200)
        self.assertIn("event-stream", headers.get("Content-Type", ""))
        self.assertIn(b"event: error", raw)

    def _request(
        self,
        method: str,
        path: str,
        query_string: str,
        body: dict | None = None,
        *,
        app=None,
    ) -> tuple[int, dict[str, str], bytes]:
        app = app or self.app
        environ: dict[str, object] = {}
        setup_testing_defaults(environ)
        environ["REQUEST_METHOD"] = method
        environ["PATH_INFO"] = path
        environ["QUERY_STRING"] = query_string
        raw_body = b""
        if body is not None:
            raw_body = json.dumps(body, ensure_ascii=False).encode("utf-8")
            environ["CONTENT_LENGTH"] = str(len(raw_body))
            environ["CONTENT_TYPE"] = "application/json"
        else:
            environ["CONTENT_LENGTH"] = "0"
        environ["wsgi.input"] = BytesIO(raw_body)
        captured: dict[str, object] = {}

        def start_response(status: str, headers: list[tuple[str, str]]) -> None:
            captured["status"] = status
            captured["headers"] = headers

        out = b"".join(app(environ, start_response))
        code = int(str(captured["status"]).split(" ", 1)[0])
        hdrs = dict(captured["headers"])
        return code, hdrs, out

    def _parse_sse(self, raw: bytes) -> list[tuple[str, dict[str, object]]]:
        text = raw.decode("utf-8")
        events: list[tuple[str, dict[str, object]]] = []
        for block in text.split("\n\n"):
            if not block.strip():
                continue
            name = ""
            data_line = ""
            for line in block.splitlines():
                if line.startswith("event:"):
                    name = line[6:].strip()
                elif line.startswith("data:"):
                    data_line = line[5:].strip()
            if name and data_line:
                events.append((name, json.loads(data_line)))
        return events


if __name__ == "__main__":
    unittest.main()
